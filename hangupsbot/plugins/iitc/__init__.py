import plugins
import json
import requests
import subprocess
import sys
import html
import logging

from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen
from urllib.parse import quote as urlquote
from hangups.ui.utils import get_conv_name

url = "http://localhost:31337/"
headers = {'content-type': 'application/json'}

logger = logging.getLogger(__name__)

def _initialise(bot):
    plugins.register_admin_command(["iitc", "iitcregion", "iitcdraw"])
    plugins.register_admin_command(["iitcbot"])


def iitcbot(bot, event, command=None):
    """
    Control the IITC snapshot service
    Usage: /bot iitcbot <start | stop | restart | status>
    """
    if not command or command not in ["start" , "stop" , "restart", "status" ]:
        bot.send_html_to_conversation(event.conv_id, _("<i>command not specified or invalid</i>"))
        return

    control = bot.get_config_suboption(event.conv_id, 'iitcbot_control')
    if not control:
        control = [ "/usr/bin/sudo", "/bin/systemctl", "<command>", "iitcbot" ]

    for index,term in enumerate(control):
        if term == "<command>":
            control[index] = command

    bot.send_html_to_conversation(event.conv_id, _("<i>Requesting {}, please wait</i>").format(command))

    logger.info("executing " + " ".join(control))
    try:
        out = subprocess.check_output(control).decode("utf-8")
    except subprocess.CalledProcessError as e:
        out = e.output.decode("utf-8")

    if (len(out) > 0):
        yield from bot.coro_send_to_user_and_conversation(
            event.user.id_.chat_id,
            event.conv_id,
            html.escape(out, quote=True).replace("`", "\`"),
            _("<i>{}, command output sent to you</i>").format(event.user.full_name))


def iitc(bot, event, *args):
    """
    Display an IITC screenshot for the requested region
    Usage: /bot iitc [region] (if no region specified, list available regions)

    Related commands: iitcregion, iitcdraw
    """

    if not args:
        bot.send_html_to_conversation(event.conv_id, _("<i>no region specified</i>"))
        return

    memory = bot.get_memory_option('iitcregion')
    for region in args:
        region = region.lower()
        if region in memory:
            payload = json.loads(json.dumps(memory[region]))
            payload["name"] = region
            payload["callback"] = "https://localhost:9002/{}".format(event.conv_id)
            print(payload)
            headers = {'content-type': 'application/json'}
            try:
              r = requests.post(url, data = json.dumps(payload), headers = headers, verify=False)
              bot.send_html_to_conversation(event.conv_id, _("<i>loading {}, please wait</i>").format(region))
            except requests.exceptions.ConnectionError:
              bot.send_html_to_conversation(event.conv_id, _("<i>iitcbot not ready</i>"))
        else:
            bot.send_html_to_conversation(event.conv_id, _("<i>region {} not defined</i>").format(region))

def iitcregion(bot, event, name=None, url=None):
    """
    Adds a region to the bot's memory.
    Usage: /bot iitcregion <name> <intel_url>
    """
    if not name or not url:
        memory = bot.get_memory_option('iitcregion')
        memory = list(memory.keys())
        memory.sort()
        regions = ", ".join(memory)
        bot.send_html_to_conversation(event.conv_id, _("<i>{}: configured regions: {}</i>").format(event.user.full_name,
regions))
        return
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    latlng = list(map(float, query['ll'][0].split(',')))
    zoom = int(query['z'][0])
    obj = {"latlng":latlng, "zoom":zoom}
    name = name.lower()
    if not bot.memory.exists(['iitcregion']):
        # create conv_data if it does not exist
        bot.memory.set_by_path(['iitcregion'], {})
    bot.memory.set_by_path(["iitcregion", name], obj)
    bot.memory.save()
    bot.send_html_to_conversation(event.conv_id, _("<i>{}: {} saved</i>").format(event.user.full_name, name))

def iitcdraw(bot, event, action=None, name=None, plan=None):
    """
    Stores json for field plans, and adds or removes them from the intel map
    Usage: /bot iitcdraw [<plan>]		- add polygon plan to map
           /bot iitcdraw clear			- remove polygon plan from map
           /bot iitcdraw store <plan> <polygon> - define a polygon plan
    """
    if not bot.memory.exists(['iitcdraw']):
        # create conv_data if it does not exist
        bot.memory.set_by_path(['iitcdraw'], {})

    if not action:
        memory = bot.get_memory_option('iitcdraw')
        plans = ', '.join(memory)
        bot.send_html_to_conversation(event.conv_id, _("<i>{}: configured plans: {}</i>").format(event.user.full_name, plans))
        return
    elif action == 'store' and name and plan:
        name = name.lower()
        try:
            plan = json.loads(plan)
        except ValueError:
            pass
        bot.memory.set_by_path(["iitcdraw", name], plan)
        bot.memory.save()
        bot.send_html_to_conversation(event.conv_id, _("<i>{}: {} saved</i>").format(event.user.full_name, name))
    elif action == 'clear':
        try:
            r = requests.post(url, data = json.dumps({"action":"clear"}), headers = headers, verify=False)
            bot.send_html_to_conversation(event.conv_id, _("<i>current plan cleared</i>"))
        except requests.exceptions.ConnectionError:
            bot.send_html_to_conversation(event.conv_id, _("<i>iitcbot not ready</i>"))
    else:
        action = action.lower()
        try:
            plan = bot.memory.get_by_path(["iitcdraw", action])
        except KeyError:
            bot.send_html_to_conversation(event.conv_id, _("<i>no such plan: {}</i>").format(action))
            return
        if type(plan) is list:
            plan = json.dumps(plan)
        payload = {"action": "load", "json": plan}
        try:
            r = requests.post(url, data = json.dumps(payload), headers = headers, verify=False)
            bot.send_html_to_conversation(event.conv_id, _("<i>{} sent to iitcbot</i>").format(action))
        except requests.exceptions.ConnectionError:
            bot.send_html_to_conversation(event.conv_id, _("<i>iitcbot not ready</i>"))
