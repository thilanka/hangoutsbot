#!/usr/bin/env python3
import gettext, os, sys, argparse, logging, shutil, asyncio, time, signal

gettext.install('hangupsbot', localedir=os.path.join(os.path.dirname(__file__), 'locale'))

import appdirs

import hangups

from hangups.schemas import OffTheRecordStatus

import config
import handlers
import version

from commands import command
from handlers import handler # shim for handler decorator

from utils import simple_parse_to_segments, class_from_name

import permamem
import hooks
import sinks
import plugins

from permamem import conversation_memory


LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

CONSOLE_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
CONSOLE_DATE_FORMAT = '%H:%M:%S'


class SuppressHandler(Exception):
    pass

class SuppressAllHandlers(Exception):
    pass

class SuppressEventHandling(Exception):
    pass

class HangupsBotExceptions:
    def __init__(self):
        self.SuppressHandler = SuppressHandler
        self.SuppressAllHandlers = SuppressAllHandlers
        self.SuppressEventHandling = SuppressEventHandling


class FakeConversation(object):
    def __init__(self, _client, id_):
        self._client = _client
        self.id_ = id_

    @asyncio.coroutine
    def send_message(self, segments, image_id=None, otr_status=None):
        with (yield from asyncio.Lock()):
            if segments:
                serialised_segments = [seg.serialize() for seg in segments]
            else:
                serialised_segments = None

            yield from self._client.sendchatmessage(
                self.id_, serialised_segments,
                image_id=image_id, otr_status=otr_status
            )


class StatusEvent:
    """base class for all non-ConversationEvent
        TypingEvent
        WatermarkEvent
    """
    def __init__(self, bot, state_update_event):
        self.conv_event = state_update_event
        self.conv_id = state_update_event.conversation_id.id_
        self.conv = None
        self.event_id = None
        self.user_id = None
        self.user = None
        self.timestamp = None
        self.text = ''
        self.from_bot = False


class TypingEvent(StatusEvent):
    def __init__(self, bot, state_update_event):
        super().__init__(bot, state_update_event)
        self.user_id = state_update_event.user_id
        self.timestamp = state_update_event.timestamp
        self.user = bot.get_hangups_user(state_update_event.user_id)
        if self.user.is_self:
            self.from_bot = True
        self.text = "typing"


class WatermarkEvent(StatusEvent):
    def __init__(self, bot, state_update_event):
        super().__init__(bot, state_update_event)
        self.user_id = state_update_event.participant_id
        self.timestamp = state_update_event.latest_read_timestamp
        self.user = bot.get_hangups_user(state_update_event.participant_id)
        if self.user.is_self:
            self.from_bot = True
        self.text = "watermark"


class ConversationEvent(object):
    """Conversation event"""
    def __init__(self, bot, conv_event):
        self.conv_event = conv_event
        self.conv_id = conv_event.conversation_id
        self.conv = bot._conv_list.get(self.conv_id)
        self.event_id = conv_event.id_
        self.user_id = conv_event.user_id
        self.user = self.conv.get_user(self.user_id)
        self.timestamp = conv_event.timestamp
        self.text = conv_event.text.strip() if isinstance(conv_event, hangups.ChatMessageEvent) else ''

    def print_debug(self, bot=None):
        """Print informations about conversation event"""
        print('eid/dtime: {}/{}'.format(self.event_id, self.timestamp.astimezone(tz=None).strftime('%Y-%m-%d %H:%M:%S')))
        if not bot:
            # don't crash on old usage, instruct dev to supply bot
            print('cid/cname: {}/undetermined, supply parameter: bot'.format(self.conv_id))
        else:
            print('cid/cname: {}/{}'.format(self.conv_id, bot.conversations.get_name(self.conv)))
        if self.user_id.chat_id == self.user_id.gaia_id:
            print('uid/uname: {}/{}'.format(self.user_id.chat_id, self.user.full_name))
        else:
            print('uid/uname: {}!{}/{}'.format(self.user_id.chat_id, self.user_id.gaia_id, self.user.full_name))
        print('txtlen/tx: {}/{}'.format(len(self.text), self.text))
        print('eventdump: completed --8<--')


class HangupsBot(object):
    """Hangouts bot listening on all conversations"""
    def __init__(self, cookies_path, config_path, max_retries=5, memory_file=None):
        self.Exceptions = HangupsBotExceptions()

        self.shared = {} # safe place to store references to objects

        self._client = None
        self._cookies_path = cookies_path
        self._max_retries = max_retries

        # These are populated by on_connect when it's called.
        self._conv_list = None # hangups.ConversationList
        self._user_list = None # hangups.UserList
        self._handlers = None # handlers.py::EventHandler

        self._cache_event_id = {} # workaround for duplicate events

        self._locales = {}

        # Load config file
        self.config = config.Config(config_path)

        # set localisation if anything defined in config.language or ENV[HANGOUTSBOT_LOCALE]
        _language = self.get_config_option('language') or os.environ.get("HANGOUTSBOT_LOCALE")
        if _language:
            self.set_locale(_language)

        # load in previous memory, or create new one
        self.memory = None
        if memory_file:
            _failsafe_backups = int(self.get_config_option('memory-failsafe_backups') or 3)
            _save_delay = int(self.get_config_option('memory-save_delay') or 1)

            logging.info("memory = {}, failsafe = {}, delay = {}".format(
                memory_file, _failsafe_backups, _save_delay))

            self.memory = config.Config(memory_file, failsafe_backups=_failsafe_backups, save_delay=_save_delay)
            if not os.path.isfile(memory_file):
                try:
                    logging.info("creating memory file: {}".format(memory_file))
                    self.memory.force_taint()
                    self.memory.save()

                except (OSError, IOError) as e:
                    logging.exception('FAILED TO CREATE DEFAULT MEMORY FILE')
                    sys.exit()

        # Handle signals on Unix
        # (add_signal_handler is not implemented on Windows)
        try:
            loop = asyncio.get_event_loop()
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, lambda: self.stop())
        except NotImplementedError:
            pass

    def set_locale(self, language_code, reuse=True):
        if not reuse or language_code not in self._locales:
            try:
                self._locales[language_code] = gettext.translation('hangupsbot', localedir=os.path.join(os.path.dirname(__file__), 'locale'), languages=[language_code])
                logging.debug("locale loaded: {}".format(language_code))
            except OSError:
                logging.exception("no translation for {}".format(language_code))

        if language_code in self._locales:
            self._locales[language_code].install()
            logging.info("locale: {}".format(language_code))
            return True

        else:
            logging.warning("LOCALE: {}".format(language_code))
            return False


    def register_shared(self, id, objectref, forgiving=False):
        if id in self.shared:
            message = _("{} already registered in shared").format(id)
            if forgiving:
                logging.info(message)
            else:
                raise RuntimeError(message)

        self.shared[id] = objectref
        plugins.tracking.register_shared(id, objectref, forgiving=forgiving)

    def call_shared(self, id, *args, **kwargs):
        object = self.shared[id]
        if hasattr(object, '__call__'):
            return object(*args, **kwargs)
        else:
            return object

    def login(self, cookies_path):
        """Login to Google account"""
        # Authenticate Google user and save auth cookies
        # (or load already saved cookies)
        try:
            cookies = hangups.auth.get_auth_stdin(cookies_path)
            return cookies

        except hangups.GoogleAuthError as e:
            logging.exception("LOGIN FAILED")
            return False

    def run(self):
        """Connect to Hangouts and run bot"""
        cookies = self.login(self._cookies_path)
        if cookies:
            # Start asyncio event loop
            loop = asyncio.get_event_loop()

            # initialise pluggable framework
            hooks.load(self)
            sinks.start(self)

            # Connect to Hangouts
            # If we are forcefully disconnected, try connecting again
            for retry in range(self._max_retries):
                try:
                    # create Hangups client (recreate if its a retry)
                    self._client = hangups.Client(cookies)
                    self._client.on_connect.add_observer(self._on_connect)
                    self._client.on_disconnect.add_observer(self._on_disconnect)

                    loop.run_until_complete(self._client.connect())
                    sys.exit(0)
                except Exception as e:
                    logging.exception("CLIENT: unrecoverable low-level error")
                    print(_('Client unexpectedly disconnected:\n{}').format(e))
                    print(_('Waiting {} seconds...').format(5 + retry * 5))
                    time.sleep(5 + retry * 5)
                    print(_('Trying to connect again (try {} of {})...').format(retry + 1, self._max_retries))

            print(_('Maximum number of retries reached! Exiting...'))
        sys.exit(1)

    def stop(self):
        """Disconnect from Hangouts"""
        asyncio.async(
            self._client.disconnect()
        ).add_done_callback(lambda future: future.result())

    def send_message(self, conversation, text, context=None):
        """"Send simple chat message"""
        self.send_message_segments(
            conversation,
            [hangups.ChatMessageSegment(text)],
            context)

    def send_message_parsed(self, conversation, html, context=None):
        segments = simple_parse_to_segments(html)
        self.send_message_segments(conversation, segments, context)

    def send_message_segments(self, conversation, segments, context=None, image_id=None):
        """Send chat message segments"""

        # Ignore if the user hasn't typed a message.
        if type(segments) is list and len(segments) == 0:
            return

        # add default context if none exists
        if not context:
            context = {}
        if "base" not in context:
            context["base"] = self._messagecontext_legacy()

        # reduce conversation to the only things we need: conversation_id
        if isinstance(conversation, (FakeConversation, hangups.conversation.Conversation)):
            conversation_id = conversation.id_
        elif isinstance(conversation, str):
            conversation_id = conversation
        else:
            raise ValueError(_('could not identify conversation id'))

        # determine OTR status based on conversation memory
        otr_status = OffTheRecordStatus.ON_THE_RECORD
        try:
            if self.conversations.catalog[conversation_id]["history"]:
                otr_status = OffTheRecordStatus.ON_THE_RECORD
            else:
                otr_status = OffTheRecordStatus.OFF_THE_RECORD
        except KeyError:
            # rare scenario where a conversation was not refreshed
            # once the initial message goes through, convmem will be updated
            logging.warning("SEND_MESSAGE_SEGMENTS(): could not determine otr for {}".format(
                conversation_id))

        # by default, a response always goes into a single conversation only
        broadcast_list = [(conversation_id, segments)]

        asyncio.async(
            self._begin_message_sending(broadcast_list, context, image_id=image_id, otr_status=otr_status)
        ).add_done_callback(self._on_message_sent)

    @asyncio.coroutine
    def _begin_message_sending(self, broadcast_list, context, image_id=None, otr_status=None):
        try:
            yield from self._handlers.run_pluggable_omnibus("sending", self, broadcast_list, context)
        except self.Exceptions.SuppressEventHandling:
            logging.info("message sending: SuppressEventHandling")
            return
        except:
            raise

        logging.debug("message sending: global context = {}".format(context))

        for response in broadcast_list:
            logging.debug("message sending: {}".format(response[0]))

            # send messages using FakeConversation as a workaround
            _fc = FakeConversation(self._client, response[0])
            yield from _fc.send_message(response[1], image_id=image_id, otr_status=otr_status)

    def list_conversations(self):
        """List all active conversations"""
        try:
            _all_conversations = self._conv_list.get_all()
            convs = _all_conversations
            logging.info("list_conversations(): {} returned".format(len(convs)))
        except Exception as e:
            logging.exception("LIST_CONVERSATIONS(): failed")
            raise

        return convs

    def get_hangups_user(self, user_id):
        hangups_user = False

        if isinstance(user_id, str):
            chat_id = user_id
            gaia_id = user_id
        else:
            chat_id = user_id.chat_id
            gaia_id = user_id.gaia_id

        UserID = hangups.user.UserID(chat_id=chat_id, gaia_id=gaia_id)

        """from hangups, if it exists"""
        if not hangups_user:
            try:
                hangups_user = self._user_list._user_dict[UserID]
            except KeyError as e:
                pass

        """from permanent conversation user/memory"""
        if not hangups_user:
            if self.memory.exists(["user_data", chat_id, "_hangups"]):
                _cached = self.memory.get_by_path(["user_data", chat_id, "_hangups"])

                hangups_user = hangups.user.User(
                    UserID, 
                    _cached["full_name"],
                    _cached["first_name"],
                    _cached["photo_url"],
                    _cached["emails"],
                    _cached["is_self"] )

        """if all else fails, create an "unknown" user"""
        if not hangups_user:
            hangups_user = hangups.user.User(
                UserID,
                "unknown user",
                None,
                None,
                [],
                False )

        return hangups_user


    def get_users_in_conversation(self, conv_ids):
        """list all unique users in supplied conv_id or list of conv_ids"""

        if isinstance(conv_ids, str):
            conv_ids = [conv_ids]
        conv_ids = list(set(conv_ids))

        all_users = {}
        for convid in conv_ids:
            conv_data = self.conversations.catalog[convid]
            for chat_id in conv_data["participants"]:
                all_users[chat_id] = self.get_hangups_user(chat_id) # by key for uniqueness

        all_users = list(all_users.values())

        return all_users

    def get_config_option(self, option):
        return self.config.get_option(option)

    def get_config_suboption(self, conv_id, option):
        return self.config.get_suboption("conversations", conv_id, option)

    def get_memory_option(self, option):
        return self.memory.get_option(option)

    def get_memory_suboption(self, user_id, option):
        return self.memory.get_suboption("user_data", user_id, option)

    def user_memory_set(self, chat_id, keyname, keyvalue):
        self.initialise_memory(chat_id, "user_data")
        self.memory.set_by_path(["user_data", chat_id, keyname], keyvalue)
        self.memory.save()

    def user_memory_get(self, chat_id, keyname):
        value = None
        try:
            self.initialise_memory(chat_id, "user_data")
            value = self.memory.get_by_path(["user_data", chat_id, keyname])
        except KeyError:
            pass
        return value

    def conversation_memory_set(self, conv_id, keyname, keyvalue):
        self.initialise_memory(conv_id, "conv_data")
        self.memory.set_by_path(["conv_data", conv_id, keyname], keyvalue)
        self.memory.save()

    def conversation_memory_get(self, conv_id, keyname):
        value = None
        try:
            self.initialise_memory(conv_id, "conv_data")
            value = self.memory.get_by_path(["conv_data", conv_id, keyname])
        except KeyError:
            pass
        return value

    def print_conversations(self):
        print(_('Conversations:'))
        for c in self.list_conversations():
            print('  {} ({}) u:{}'.format(self.conversations.get_name(c), c.id_, len(c.users)))
            for u in c.users:
                print('    {} ({}) {}'.format(u.first_name, u.full_name, u.id_.chat_id))
        print()

    def get_1on1_conversation(self, chat_id):
        """find a 1-to-1 conversation with specified user
        maintained for functionality with older plugins that do not use get_1to1()
        """
        self.initialise_memory(chat_id, "user_data")

        if self.memory.exists(["user_data", chat_id, "optout"]):
            if self.memory.get_by_path(["user_data", chat_id, "optout"]):
                return False

        conversation = None

        if self.memory.exists(["user_data", chat_id, "1on1"]):
            conversation_id = self.memory.get_by_path(["user_data", chat_id, "1on1"])
            conversation = FakeConversation(self._client, conversation_id)
            logging.info(_("memory: {} is 1on1 with {}").format(conversation_id, chat_id))
        else:
            for c in self.list_conversations():
                if len(c.users) == 2:
                    for u in c.users:
                        if u.id_.chat_id == chat_id:
                            conversation = c
                            break

            if conversation is not None:
                # remember the conversation so we don't have to do this again
                self.memory.set_by_path(["user_data", chat_id, "1on1"], conversation.id_)
                self.memory.save()

        return conversation


    @asyncio.coroutine
    def get_1to1(self, chat_id):
        """find/create a 1-to-1 conversation with specified user
        config.autocreate-1to1 = true to enable conversation creation, otherwise will revert to
            legacy behaviour of finding an existing 1-to-1
        config.bot_introduction = "some text or html" to show to users when a new conversation
            is created - "{0}" will be substituted with first bot alias
        """
        self.initialise_memory(chat_id, "user_data")

        if self.memory.exists(["user_data", chat_id, "optout"]):
            if self.memory.get_by_path(["user_data", chat_id, "optout"]):
                return False

        conversation = None

        if self.memory.exists(["user_data", chat_id, "1on1"]):
            conversation_id = self.memory.get_by_path(["user_data", chat_id, "1on1"])
            conversation = FakeConversation(self._client, conversation_id)
            logging.info("get_1on1: remembered {} for {}".format(conversation_id, chat_id))
        else:
            if self.get_config_option('autocreate-1to1'):
                """create a new 1-to-1 conversation with the designated chat id
                send an introduction message as well to the user as part of the chat creation
                """
                logging.info("get_1on1: creating 1to1 with {}".format(chat_id))
                try:
                    introduction = self.get_config_option('bot_introduction')
                    if not introduction:
                        introduction =_("<i>Hi there! I'll be using this channel to send private "
                                        "messages and alerts. "
                                        "For help, type <b>{0} help</b>. "
                                        "To keep me quiet, reply with <b>{0} optout</b>.</i>").format(self._handlers.bot_command[0])
                    response = yield from self._client.createconversation([chat_id])
                    new_conversation_id = response['conversation']['id']['id']
                    self.send_html_to_conversation(new_conversation_id, introduction)
                    conversation = FakeConversation(self._client, new_conversation_id)
                except Exception as e:
                    logging.exception("GET_1TO1: failed to create 1-to-1 for user {}".format(chat_id))
            else:
                """legacy behaviour: user must say hi to the bot first
                this creates a conversation entry in self._conv_list (even if the bot receives
                a chat invite only - a message sent on the channel auto-accepts the invite)
                """
                logging.info("get_1on1: searching for existing 1to1 with {}".format(chat_id))
                for c in self.list_conversations():
                    if len(c.users) == 2:
                        for u in c.users:
                            if u.id_.chat_id == chat_id:
                                conversation = c
                                break

            if conversation is not None:
                # remember the conversation so we don't have to do this again
                logging.info("get_1on1: determined {} for {}".format(conversation.id_, chat_id))
                self.memory.set_by_path(["user_data", chat_id, "1on1"], conversation.id_)
                self.memory.save()

        return conversation


    def initialise_memory(self, chat_id, datatype):
        modified = False

        if not self.memory.exists([datatype]):
            # create the datatype grouping if it does not exist
            self.memory.set_by_path([datatype], {})
            modified = True

        if not self.memory.exists([datatype, chat_id]):
            # create the memory
            self.memory.set_by_path([datatype, chat_id], {})
            modified = True

        return modified

    def messagecontext(self, source, importance, tags):
        return {
            "source": source,
            "importance": importance,
            "tags": tags
        }

    def _messagecontext_legacy(self):
        return self.messagecontext("unknown", 50, ["legacy"])

    def _on_message_sent(self, future):
        """Handle showing an error if a message fails to send"""
        try:
            future.result()
        except hangups.NetworkError:
            logging.exception("FAILED TO SEND MESSAGE")

    @asyncio.coroutine
    def _on_connect(self, initial_data):
        """handle connection/reconnection"""

        logging.debug("connected")

        self._handlers = handlers.EventHandler(self)
        handlers.handler.set_bot(self) # shim for handler decorator

        self._user_list = yield from hangups.user.build_user_list(self._client,
                                                                  initial_data)

        self._conv_list = hangups.ConversationList(self._client,
                                                   initial_data.conversation_states,
                                                   self._user_list,
                                                   initial_data.sync_timestamp)

        self.conversations = yield from permamem.initialise_permanent_memory(self)

        plugins.load(self, command)

        self._conv_list.on_event.add_observer(self._on_event)
        self._client.on_state_update.add_observer(self._on_status_changes)

        logging.info("bot initialised")


    def _on_status_changes(self, state_update):
        if state_update.typing_notification is not None:
            asyncio.async(
                self._handlers.handle_typing_notification(
                    TypingEvent(self, state_update.typing_notification)
                )
            ).add_done_callback(lambda future: future.result())

        if state_update.watermark_notification is not None:
            asyncio.async(
                self._handlers.handle_watermark_notification(
                    WatermarkEvent(self, state_update.watermark_notification)
                )
            ).add_done_callback(lambda future: future.result())


    @asyncio.coroutine
    def _on_event(self, conv_event):
        """Handle conversation events"""

        self._execute_hook("on_event", conv_event)

        if self.get_config_option('workaround.duplicate-events'):
            if conv_event.id_ in self._cache_event_id:
                logging.warning("duplicate event {} ignored".format(conv_event.id_))
                return

            self._cache_event_id = {k: v for k, v in self._cache_event_id.items() if v > time.time()-3}
            self._cache_event_id[conv_event.id_] = time.time()

            logging.info("duplicate events workaround: event id = {} timestamp = {}".format(
                conv_event.id_, conv_event.timestamp))

        event = ConversationEvent(self, conv_event)

        yield from self.conversations.update(self._conv_list.get(conv_event.conversation_id), 
                                             source="event")

        if isinstance(conv_event, hangups.ChatMessageEvent):
            self._execute_hook("on_chat_message", event)
            asyncio.async(
                self._handlers.handle_chat_message(event)
            ).add_done_callback(lambda future: future.result())

        elif isinstance(conv_event, hangups.MembershipChangeEvent):
            self._execute_hook("on_membership_change", event)
            asyncio.async(
                self._handlers.handle_chat_membership(event)
            ).add_done_callback(lambda future: future.result())

        elif isinstance(conv_event, hangups.RenameEvent):
            self._execute_hook("on_rename", event)
            asyncio.async(
                self._handlers.handle_chat_rename(event)
            ).add_done_callback(lambda future: future.result())

        elif type(conv_event) is hangups.conversation_event.ConversationEvent:
            if conv_event._event.hangout_event:
                asyncio.async(
                    self._handlers.handle_call(event)
                ).add_done_callback(lambda future: future.result())

        else:
            logging.warning("_on_event(): unrecognised event type: {}".format(type(conv_event)))


    def _execute_hook(self, funcname, parameters=None):
        for hook in self._hooks:
            method = getattr(hook, funcname, None)
            if method:
                try:
                    method(parameters)
                except Exception as e:
                    logging.exception("HOOKS: {}".format(hook))

    def _on_disconnect(self):
        """Handle disconnecting"""
        logging.info('Connection lost!')

    def external_send_message(self, conversation_id, text):
        """
        LEGACY
            use send_html_to_conversation()
        """
        logging.warning('[DEPRECATED]: use send_html_to_conversation() instead of external_send_message()')
        self.send_html_to_conversation(conversation_id, text)

    def external_send_message_parsed(self, conversation_id, html):
        """
        LEGACY
            use send_html_to_conversation()
        """
        logging.warning('[DEPRECATED]: use send_html_to_conversation() instead of external_send_message_parsed()')
        self.send_html_to_conversation(conversation_id, html)

    def send_html_to_conversation(self, conversation_id, html, context=None):
        logging.info("sending message to conversation {}".format(conversation_id))
        self.send_message_parsed(conversation_id, html, context)

    def send_html_to_user(self, user_id, html, context=None):
        conversation = self.get_1on1_conversation(user_id)
        if not conversation:
            logging.warning("1-to-1 not found for {}".format(user_id))
            return False

        logging.info("sending message to user {}".format(user_id))
        self.send_message_parsed(conversation, html, context)
        return True

    def send_html_to_user_or_conversation(self, user_id_or_conversation_id, html, context=None):
        """Attempts send_html_to_user. If failed, attempts send_html_to_conversation"""
        logging.warning('[DEPRECATED] use send_html_to_conversation() or send_html_to_user() instead of send_html_to_user_or_conversation()')
        # NOTE: Assumption that a conversation_id will never match a user_id
        if not self.send_html_to_user(user_id_or_conversation_id, html, context):
            self.send_html_to_conversation(user_id_or_conversation_id, html, context)

    def send_html_to_user_and_conversation(self, user, conversation, html_private, html_public=None, context=None):
        """
        If the command was issued on a public channel, respond to the user
        privately and optionally send a short public response back as well.
        """
        if isinstance(user, hangups.user.User):
            chat_id = user.id_.chat_id
        else:
            # assume isinstance(user, str)
            chat_id = user

        if isinstance(conversation, (FakeConversation, hangups.conversation.Conversation)):
            conv_id = conversation.id_
        else:
            # assume isinstance(conversation, str)
            conv_id = conversation

        asyncio.async(
            self.coro_send_to_user_and_conversation(chat_id,
                                                    conv_id,
                                                    html_private,
                                                    html_public,
                                                    context=context)
        ).add_done_callback(lambda future: future.result())

    @asyncio.coroutine
    def coro_send_to_user_and_conversation(self, chat_id, conv_id, html_private, html_public=False, context=None):
        """
        If the command was issued on a public channel, respond to the user
        privately and optionally send a short public response back as well.
        """
        conv_1on1_initiator = yield from self.get_1to1(chat_id)

        full_name = _("Unidentified User")
        if self.memory.exists(["user_data", chat_id, "_hangups"]):
            full_name = self.memory["user_data"][chat_id]["_hangups"]["full_name"]

        responses = {
            "standard":
                False, # no public messages
            "optout":
                _("<i>{}, you are currently opted-out. Private message me or enter <b>{} optout</b> to get me to talk to you.</i>")
                    .format(full_name, min(self._handlers.bot_command, key=len)),
            "no1to1":
                _("<i>{}, before I can help you, you need to private message me and say hi.</i>")
                    .format(full_name, min(self._handlers.bot_command, key=len))
        }

        if isinstance(html_public, dict):
            responses = dict
        elif isinstance(html_public, list):
            keys = ["standard", "optout", "no1to1"]
            for supplied in html_public:
                responses[keys.pop(0)] = supplied
        else:
            # isinstance(html_public, str)
            responses["standard"] = html_public

        public_message = False

        if conv_1on1_initiator:
            """always send actual html as a private message"""
            self.send_message_parsed(conv_1on1_initiator, html_private)
            if conv_1on1_initiator.id_ != conv_id and responses["standard"]:
                """send a public message, if supplied"""
                public_message = responses["standard"]

        else:
            if type(conv_1on1_initiator) is bool and responses["optout"]:
                public_message = responses["optout"]

            elif responses["no1to1"]:
                # type(conv_1on1_initiator) is NoneType
                public_message = responses["no1to1"]

        if public_message:
            self.send_message_parsed(conv_id, public_message, context=context)

    def user_self(self):
        myself = {
            "chat_id": None,
            "full_name": None,
            "email": None
        }
        User = self._user_list._self_user

        myself["chat_id"] = User.id_.chat_id

        if User.full_name: myself["full_name"] = User.full_name
        if User.emails and User.emails[0]: myself["email"] = User.emails[0]

        return myself


def main():
    """Main entry point"""
    # Build default paths for files.
    dirs = appdirs.AppDirs('hangupsbot', 'hangupsbot')
    default_log_path = os.path.join(dirs.user_log_dir, 'hangupsbot.log')
    default_cookies_path = os.path.join(dirs.user_data_dir, 'cookies.json')
    default_config_path = os.path.join(dirs.user_config_dir, 'config.json')
    default_memory_path = os.path.join(dirs.user_data_dir, 'memory.json')

    # Configure argument parser
    parser = argparse.ArgumentParser(prog='hangupsbot',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-d', '--debug', action='store_true',
                        help=_('log detailed debugging messages'))
    parser.add_argument('--log', default=default_log_path,
                        help=_('log file path'))
    parser.add_argument('--cookies', default=default_cookies_path,
                        help=_('cookie storage path'))
    parser.add_argument('--memory', default=default_memory_path,
                        help=_('memory storage path'))
    parser.add_argument('--config', default=default_config_path,
                        help=_('config storage path'))
    parser.add_argument('--version', action='version', version='%(prog)s {}'.format(version.__version__),
                        help=_('show program\'s version number and exit'))
    args = parser.parse_args()

    # Create all necessary directories.
    for path in [args.log, args.cookies, args.config, args.memory]:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                sys.exit(_('Failed to create directory: {}').format(e))

    # If there is no config file in user data directory, copy default one there
    if not os.path.isfile(args.config):
        try:
            shutil.copy(os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'config.json')),
                        args.config)
        except (OSError, IOError) as e:
            sys.exit(_('Failed to copy default config file: {}').format(e))

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO

    logging.basicConfig(filename=args.log, level=log_level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    rootLogger = logging.getLogger()

    # output logs to console
    consoleHandler = logging.StreamHandler(stream=sys.stdout)
    format = logging.Formatter(CONSOLE_FORMAT, datefmt=CONSOLE_DATE_FORMAT)
    consoleHandler.setFormatter(format)
    consoleHandler.setLevel(logging.INFO)
    rootLogger.addHandler(consoleHandler)

    # asyncio's debugging logs are VERY noisy, so adjust the log level
    logging.getLogger('asyncio').setLevel(logging.WARNING)

    # hangups log is quite verbose too, suppress so we can debug the bot
    logging.getLogger('hangups').setLevel(logging.WARNING)

    # XXX: suppress erroneous WARNINGs until https://github.com/tdryer/hangups/issues/142 resolved
    logging.getLogger('hangups.conversation').setLevel(logging.ERROR)

    #requests is freakishly noisy
    logging.getLogger("requests").setLevel(logging.INFO)

    # initialise the bot
    bot = HangupsBot(args.cookies, args.config, memory_file=args.memory)

    # start the bot
    bot.run()


if __name__ == '__main__':
    main()
