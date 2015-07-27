# Hangoutsbot IITC plugin

The original author is unknown, I've been trying to trace them down,
if you recognize this as your code, please contact me.  I've done a bit
of refactoring and fixed it, but it's derrivative of someone else's work.
	-- discontent /at/ resists.org - 24 July 2015

You do not have permission to redistribute this code, it is pre-alpha,
do not share it.

## Description

This module provides an interface to Ingress Intel maps from the
hangoutsbot bot interface.

New bot commands are:

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

    /bot iitcdaemon status | start | stop | restart
      Restart the IITCbot process

By default, these commands are all restricted to bot administrators.

## Components

1. plugins/iitc
  - maintains IITC stateful data and issues commands to iitcbot
2. sinks/generic/simpledemo.py
  - listens for responses on localhost:9002
3. plugins/iitc/{iitc.js | iitcbot }
  - headless browser captureing Intel commands
  - listens for requests on localhost:31337
  - returns responses to the simpledemo sink asynchronously

## Requirements:

- http://github.com/hangoutsbot/hangupsbot (v3.6 or later)
- http://phantomjs.org (tested with v2.0)
- http://casperjs.org (tested with 1.1-beta3)

The files in this release belong in `hangoutsbot/hangupsbot/plugins/iitc`

Create the following files:

    $HOME/.config/iitcbot/authentication
      _email_ (first line)
      _password_ (second line)
      of the Google account running Intel. 2FA is not supported.

    $HOME/.config/hangupsbot/localhost.pem
      SSL private key and public certificate for localhost (in same file)

You may generate a self-signed key with:

    openssl req -new -x509 -days 365 -nodes -keyout localhost.pem -out localhost.pem

Enable the iitc plugin in your bot configuration.
Enable the generic sink in your bot config.json configuration,

which should include something like:

    "jsonrpc": [
      {
        "certfile": "/home/hangoutsbot/.config/hangupsbot/localhost.pem",
        "module": "sinks.generic.SimpleMessagePoster",
        "name": "localhost",
        "port": 9002
      }
    ],


## Daemon Management

systemd(8) `.service` files are provided for both hangoutsbot and iitcbot
for folks who use systemd as their process manager. The two bots are
independent of each other and can be configured to run under separate
uids if desired (this is reccommended).

There are two files, `hangoutsbot.service` and `iitcbot.service` in the
`examples/` subdirectory which can be used as emables for systemd service
control files. Copy them to `/etc/systemd/system/` and modify them as
you choose.

Occasionally the IITCbot will need to be restarted because of a change
to the intel site, or just a bug. When running systemd, the iitcreload
command will execute "sudo systemctl restart iitcbot"

To add sudo permissions to hangoutsbot user so it can restart iitcbot,
on a Debian type installation, you may use:

    echo "hangoutsbot ALL= NOPASSWD: /bin/systemctl restart iitcbot,/bin/systemctl start iitcbot,/bin/systemctl stop iitcbot,/bin/systemctl status iitcbot" \
	     >/etc/sudoers.d/hangoutsbot
    chmod 440 /etc/sudoers.d/hangoutsbot
    chown root.root /etc/sudoers.d/hangoutsbot

## To-Do

- [ ] ability to delete plans and region definitions
- [ ] authorization system to extend commands beyond bot administrators
- [ ] fix errors in casperjs interpretation of iitc
- [ ] eliminate cross site XHHTP vulnerability if anything upstream gets pwned
      so we can remove "--web-security=false"

