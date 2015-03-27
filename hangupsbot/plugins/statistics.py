"""
Collect statistics about users and chats and store them in memory.json
"""

import asyncio, re, time

import hangups

def _initialise(Handlers, bot=None):
    Handlers.register_handler(_handle_event_statistics, type="message")
    return ["displaystats"]

"""conversation memory"""

@asyncio.coroutine
def _handle_event_statistics(bot, event, command):
    """ Handle events, storing information about them
    """

    _store_last_active(bot, event)

    _store_message_per_minute(bot, event)

    _store_last_active_user(bot, event)

    _store_message_from_user_count(bot, event)

def _store_last_active(bot, event):
    """ Store the timestamp that the chat was last active """

    bot.conversation_memory_set(event.conv_id, 'last_active', str(time.time()))

def _store_message_per_minute(bot, event):
    """ Store the message/minute for a conversation (currently only for all time) """

    date_start = bot.conversation_memory_get(event.conv_id, 'first_active')
    if date_start is None:
        bot.conversation_memory_set(event.conv_id, 'first_active', str(time.time()))

    totalmessages = bot.conversation_memory_get(event.conv_id, 'total_messages')
    if totalmessages is None:
        bot.conversation_memory_set(event.conv_id, 'total_messages', str(1))
    else:
        bot.conversation_memory_set(event.conv_id, 'total_messages', str(int(totalmessages) + 1))

def _store_last_active_user(bot, event):
    """ Update the time that the user was last active in a chat """

    _conversation_user_memory_set(bot, event.conv_id, event.user.id_.chat_id, 'user_last_active', str(time.time()))

def _store_message_from_user_count(bot, event):
    """ Update the number of total messages that the user has sent in a conv """

    totalmessages = _conversation_user_memory_get(bot, event.conv_id, event.user.id_.chat_id, 'total_messages')
    if totalmessages is None:
        _conversation_user_memory_set(bot, event.conv_id, event.user.id_.chat_id, 'total_messages', str(1))
    else:
        _conversation_user_memory_set(bot, event.conv_id, event.user.id_.chat_id, 'total_messages', str(int(totalmessages) + 1))

def _conversation_user_memory_set(bot, conv_id, user_id, keyname, keyvalue):
    """ A derivation of bot.convsersation_memory_set() designed for storing information per user per chat """

    if not bot.memory.exists(['conv_data']):
        # create conv_data if it does not exist
        bot.memory.set_by_path(['conv_data'], {})

    if not bot.memory.exists(['conv_data', conv_id]):
        # create the conv path if it does not exist
        bot.memory.set_by_path(['conv_data', event.conv_id], {})

    if not bot.memory.exists(['conv_data', conv_id, user_id]):
        # create the memory
        bot.memory.set_by_path(['conv_data', conv_id, user_id], {})

    bot.memory.set_by_path(['conv_data', conv_id, user_id, keyname], keyvalue)
    bot.memory.save()

def _conversation_user_memory_get(bot, conv_id, user_id, keyname):
    """ A derivation of bot.convsersation_memory_get() designed for getting information per user per chat """

    value = None
    try:
        if not bot.memory.exists(['conv_data']):
            # create conv_data if it does not exist
            bot.memory.set_by_path(['conv_data'], {})

        if not bot.memory.exists(['conv_data', conv_id]):
            # create the conv path if it does not exist
            bot.memory.set_by_path(['conv_data', event.conv_id], {})

        if not bot.memory.exists(['conv_data', conv_id, user_id]):
            # create the memory
            bot.memory.set_by_path(['conv_data', conv_id, user_id], {})

        value = bot.memory.get_by_path(['conv_data', conv_id, user_id, keyname])
    except KeyError:
        pass
    return value


def displaystats(bot, event, *args):
    """ Display all the important stats """

    html = '<b>Statistics:</b><br />'

    """ Total Messages """
    totalmessages = bot.conversation_memory_get(event.conv_id, 'total_messages')
    if totalmessages is None:
        totalmessages = 0
    else:
        totalmessages = int(totalmessages)

    """ Messages/Minute """
    time_start = bot.conversation_memory_get(event.conv_id, 'first_active')
    if time_start is None:
        time_start = time.time()
    else:
        time_start = float(time_start)
    minutes_since_start = (time.time() - time_start) / 60
    messages_per_minute = totalmessages / minutes_since_start
    print("Total messages: {0}, Minutes since start: {1}".format(totalmessages, minutes_since_start))
    html += "Messages/Minute for chat: <b>{0:.2f}</b><br /><br />".format(messages_per_minute)

    """ User Last Active """
    users_in_chat = event.conv.users

    """check if synced room, if so, append on the users"""
    sync_room_list = bot.get_config_suboption(event.conv_id, 'sync_rooms')
    if sync_room_list:
        if event.conv_id in sync_room_list:
            for syncedroom in sync_room_list:
                if event.conv_id not in syncedroom:
                    users_in_chat += bot.get_users_in_conversation(syncedroom)
            users_in_chat = list(set(users_in_chat)) # make unique

    html += "<b>Activity and Contribution:</b><br />"
    fmt = '<b>{0:15}</b> | {1:>6}{2}'

    for user in users_in_chat:
        user_time = _conversation_user_memory_get(bot, event.conv_id, user.id_.chat_id, 'user_last_active')
        user_percentage = _conversation_user_memory_get(bot, event.conv_id, user.id_.chat_id, 'total_messages')
        if user_time is not None:
            time_since_last = (float(time.time()) - float(user_time))
            if time_since_last > 60:
                time_since_last = time_since_last / 60

                if time_since_last > 60:
                    time_since_last = time_since_last / 60
                    if time_since_last > 24:
                        time_since_last = time_since_last / 24
                        html += fmt.format(user.full_name, round(time_since_last, 2), 'd')
                    else:
                        html += fmt.format(user.full_name, round(time_since_last, 2), 'h')
                else:
                    html += fmt.format(user.full_name, round(time_since_last, 2), 'm')
            else:
                html += fmt.format(user.full_name, round(time_since_last, 2), 's')

            if user_percentage is not None:
                user_percentage = (int(user_percentage) / totalmessages) * 100
                html += " | {0}%<br />".format(round(user_percentage, 2))

    html += "<br />"

    bot.send_html_to_conversation(event.conv, html)
