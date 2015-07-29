# Hangoutsbot IITC plugin

## Description

This module provides an interface to Ingress Intel maps from the
hangoutsbot bot interface.

You do not have permission to redistribute this code, it is pre-alpha,
do not share it.

### Usage

This module provides new hangoutsbot commands:

    /bot iitc _region_
      Show a current intel map for the defined region

    /bot iitcregion
      List defined regions

    /bot iitcregion _region_ _intel-url_
      Define a region

    /bot iitcdraw
      Show the list of defined plans
    /bot iitcdraw _plan_ | clear
      Add a plan to the current region
    /bot iitcdraw clear
      Remove any plan from the current region
    /bot iitcdraw store _plan_ _polygon_
      Store an IITC drawtools polygon as a "plan"

    /bot iitcbot status | start | stop | restart
      Control the IITCbot process

By default, these commands are all restricted to only administrators.

### Credits

The original of this code is Daniel Cheng, it is a fork and enhancement
of his code. Credit for this idea belongs to him.

## Components

1. plugins/iitc
  - maintains IITC stateful data and issues commands to iitcbot
2. plugins/iitc/{iitc.js | iitcbot }
  - headless browser capturing Intel commands
  - listens for requests on localhost:31337
  - returns responses to the generic SimpleMessagePoster sink asynchronously

## Requirements:

- http://github.com/hangoutsbot/hangupsbot (v2.6 (2.5-staging) or later)
- http://phantomjs.org (tested with v2.0.1)
- http://casperjs.org (tested with 1.1-beta3)

The files in this release belong in `hangoutsbot/hangupsbot/plugins/iitc`

## Configuration:

### Ingress Authentication

Create an authentication file containing the e-mail and password of the
Ingress Player that will be responsible for iitcbot. Please note that
while IITCbot might now be considered loosely acceptable per private
discussions with Niantic employees, it is a headless browser and you may
get caught in an intel-ban for scraping data.

In order to not violate the ToS (multiple accounts), we strongly reccomend
that you use your actual Ingress account and not create a special account
just for iitcbot.

The first line should be the e-mail address of your Ingress account, the
second should be your password, in plain text. Two factor authentication
is not supported. This file should be read-protected from all other users,
ideally, you might consider running iitcbot under a different uid from
the Hangouts.

You may specify the location of the autentication file with
`--auth-file=path-to-file`

### Hangoutsbot Sink SSL Certificate

Create a OpenSSL .pem, that contains both the public and private keys
for this server (iitcbot will connect to localhost to return data to
hangoutsbot).

You may generate a self-signed key with:

    openssl req -new -x509 -days 365 -nodes -keyout localhost.pem -out localhost.pem

Enable the iitc plugin in your Hangoutsbot configuration.

Enable the generic sink in your Hangoutsbot config.json configuration and add

    "jsonrpc": [
      {
	"certfile": "/home/hangoutsbot/.config/hangupsbot/localhost.pem",
	"module": "sinks.generic.SimpleMessagePoster",
	"name": "localhost",
	"port": 9002
      }
    ],

### Managing IITCbot

Optionally add a section to 'config.json' to override the default commands
used to initiate start, stop, restart, or status requests to the iitcbot.

By default, a sudo / systemd environment assumed if nothing is added:

    "iitcbot_control": [ "/usr/bin/sudo", "/bin/systemctl", "<command>", "iitcbot" ]

&lt;command&gt; will be substituted with the appropriate command.

If one were to use upstart, one could specify:

    "iitcbot_control": [ "/usr/bin/sudo", "<command>", "iitcbot" ]

systemd(8) `.service` files are provided for both hangoutsbot and iitcbot
for folks who use systemd as their process manager. The two bots are
independent of each other and can be configured to run under separate uids
if desired (this is recommended).  Copy them to `/etc/systemd/system/`
and modify them as you choose.

Occasionally the IITCbot will need to be restarted because of a change
to the intel site, or just a bug.


#### sudo(8) notes

To add sudo permissions to hangoutsbot user so it can restart iitcbot,
on a Debian type installation, you might use:

    echo "hangoutsbot ALL= NOPASSWD: /bin/systemctl restart iitcbot,/bin/systemctl start iitcbot,/bin/systemctl stop iitcbot,/bin/systemctl status iitcbot" \
	     >/etc/sudoers.d/hangoutsbot
    chmod 440 /etc/sudoers.d/hangoutsbot
    chown root.root /etc/sudoers.d/hangoutsbot

## To-Do

- [ ] ability to delete plans and region definitions
- [ ] role-based authorization system to allow commands beyond bot administrators
- [ ] fix errors in casperjs interpretation of iitc
- [ ] eliminate cross site XHHTP vulnerability if anything upstream gets pwned
      so we can remove "--web-security=false"
