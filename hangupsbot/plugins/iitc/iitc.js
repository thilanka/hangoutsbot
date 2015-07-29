//
// IITC screenshot robot
//
// Last edited 2015-07-24 discontent - pre-release version - do not redistribute
// Original author unknown
//
// manual invocation
// casperjs --web-security=false --ignore-ssl-errors=true --verbose --cookies-file=iitcbot.cookies
//
// options
//   --auth-file=<path>		- location of username/password plaintext file
//				  (technically unnecessary after first run if
//				   you want to delete it for security reasons,
//				   but the cookies do eventually expire ~30d
//
//   --cookies-file=<psth>	- stores authentication cookies after first run
//
//   --ipc-file			- logging channel for IPC information
//
//   --extra-scripts=<file.js>[, <file>.js ...]
//   				- comma separated list of additional js to
//   				  inject
//
//   --highlight="<highlight>	- selected highligher level
//   				  (default "Higher Level Portals")
//
//   --basemap="<basemap>"	- selected base map
//   				  (default "Google Roads")
//
//   --logtime			- include timestamp in log files
//
//   --inactivity-timeout=<min> -  exit after x minutes of timeout
//
//
var casper = require('casper').create({
    verbose: true,
    logLevel: 'info',
});

casper.start();
casper.userAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.90 Safari/537.36');
casper.page.settings.resourceTimeout = 62 * 1000;
casper.options.retryTimeout = 2000;
casper.options.waitTimeout = 2 * 60 * 1000;
casper.viewport(1920, 1080);

var fs = require('fs');

var MINUTE_IN_MS = 60 * 1000;
var PAGE_WAIT = 40;				// 80 seconds
var iitc_snapshot = 'iitc-debug-snapshot.png';

// Command options

var iitc_authfile = '.iitcbot.authentication';
if (casper.cli.has("auth-file"))
    iitc_authfile = casper.cli.get("auth-file");

// --cookies-file is phantomjs native

var iitc_ipc_file = casper.cli.get("ipc-file");

var iitc_extra_scripts  = [];
if (casper.cli.has("extra-scripts"))
    iitc_extra_scripts = casper.cli.get("extra-scripts").split(",");

var iitc_highlight = 'Higher Level Portals';
if (casper.cli.has("highlight"))
   iitc_highlight = casper.cli.get("highlight");

var iitc_basemap = 'Google Roads';
if (casper.cli.has("basemap"))
   iitc_basemap = casper.cli.get("basemap");

var iitc_logtime = casper.cli.has("logtime");

var iitc_inactivity_timeout = casper.cli.get("inactivity-timeout");

// setup IPC/debugging dump to the outside world
if (iitc_ipc_file) {
   ipcstream = fs.open(iitc_ipc_file, 'a');
   casper.echo('Writing IPC-DATA to ' + iitc_ipc_file, 'INFO');
}

// send console logs to stdout
casper.on('remote.message', function(message) {
    if (message.match(/^IPC-DATA: /) && ipcstream) {
        ipcstream.write(message.substring(10));
	return;
    }

    casper.echo(iitc_logtime ? new Date() + " " + message : message);
});

casper.on('page.error', function(msg, trace) {
    if (typeof msg == 'object') {
        try {
            var utils = require('utils');
            msg = utils.dump(msg);
        } catch (err) {
            casper.echo('Unable to stringify', 'ERROR')
        }
    }
    casper.echo(iitc_logtime ? new Date() + " Error: " + msg : "Error: " + msg, 'ERROR');

    if (msg.indexOf("cannot continue") != -1) {
	casper.echo("IITC scripts aren't working, shutting down.", 'ERROR')
	//casper.capture(iitcsnap);
	casper.exit(1);
    }
});

casper.thenOpen('https://ingress.com/intel');
casper.thenBypassUnless(function checkNeedsSignin() {
    var needSignIn = this.evaluate(function() {
        return __utils__.getElementByXPath('.//a[starts-with(.,"Sign in")]');
    });
    return needSignIn;
}, 4);

// Sign In
// We do not support 2 factor authentication, but code updated to support
// new google two-page login method and pull authentication informmation
// from an external file.

var iitc_password; // XXX refactor so never globally scoped

casper.thenOpen('https://www.google.com/accounts/ServiceLogin?service=ah&passive=true&continue=https://appengine.google.com/_ah/conflogin%3Fcontinue%3Dhttps://www.ingress.com/intel&ltmpl=',
    function sendEmail() {
        var email, password;

        if (fs.isReadable(iitc_authfile)) {
            auth = fs.open(iitc_authfile, { mode: 'r' });
            if (!auth.atEnd())
                email = auth.readLine();
            if (!auth.atEnd())
                password = auth.readLine();
            auth.close();
        }

        if (email === undefined || password === undefined) {
            casper.echo('Unable to read IITC authentication information from ' + iitcauth, 'ERROR');
            this.exit(1);
        }

        this.sendKeys("#Email", email);
        this.click("#next");

        iitc_password = password;
    });

casper.waitForSelector('#Passwd', function sendPassword() {
    this.sendKeys("#Passwd", iitc_password);
    this.click("#signIn");
    iitc_password = undefined;
});

casper.waitForUrl(/https:\/\/www\.ingress\.com\/intel/);
casper.then(function saveCookies() {
    var cookies = this.page.cookies;

    // save the cookies for fast login and avoiding authentication triggers
    for (var i in cookies) {
        if (cookies[i].name === 'csrftoken') {
            this.page.addCookie({
                name: 'csrftoken',
                value: cookies[i].value,
                domain: 'www.ingress.com',
                path: '/'
            });
        }
        if (cookies[i].name === 'SACSID') {
            this.page.addCookie({
                name: 'SACSID',
                value: cookies[i].value,
                domain: 'www.ingress.com',
                path: '/',
                httponly: true,
                secure: true
            });
        }
    }
});

// Inject IITC
casper.then(function injectIITC() {
    // inject standard IITC remote scripts, if any
    this.evaluate(function() {
        var head = document.getElementsByTagName('head')[0];

        var remote_base = 'https://secure.jonatkins.com/iitc/test/';
        var remote_scripts = [
            'total-conversion-build.user.js',
            'plugins/privacy-view.user.js',
            'plugins/portal-highlighter-high-level.user.js',
            'plugins/portal-level-numbers.user.js',
            'plugins/draw-tools.user.js',
            'plugins/cross_link.user.js',
            'plugins/done-links.user.js',
            'plugins/player-tracker.user.js'
        ];

        for (i in remote_scripts) {
            var script = document.createElement('script');
            script.type = 'text/javascript';
            script.src = remote_base + remote_scripts[i];
            head.appendChild(script);
        }
    });

    var local_base = 'ingress-intel-total-conversion/build/local/';
    var local_scripts = [
/*
        'total-conversion-build.user.js',
        'plugins/privacy-view.user.js',
        'plugins/portal-highlighter-high-level.user.js',
        'plugins/portal-level-numbers.user.js',
        'plugins/draw-tools.user.js',
        'plugins/cross_link.user.js',
        'plugins/done-links.user.js',
        'plugins/player-tracker.user.js',

        // nonstandard local build
        'plugins/better-show-more.user.js',
        'plugins/iitc-advanced-player-tracker.user.js',
        'plugins/iitc-custom-player-icons.user.js',
        'plugins/iitc-hide-ui.user.js'
*/
    ];

    // inject local IITC build
    function load_iitcbot_scripts(scripts, base) {
	var index;
	for (index in scripts) {
	    casper.echo("Loading " + scripts[index], 'INFO');
	    var success = casper.page.injectJs(base + scripts[index]);
	    if (success) {
		casper.echo(scripts[index] + " loaded", 'INFO');
	    } else {
		casper.echo(scripts[index] + " failed to load!", 'ERROR');
	    }
	}
    };

    load_iitcbot_scripts(local_scripts, local_base);
    load_iitcbot_scripts(iitc_extra_scripts, '');
});


// wait for IITC to fully load
casper.waitFor(function checkIITCLoaded() {
    var iitcLoaded = this.evaluate(function() {
        return window.iitcLoaded;
    });
    return iitcLoaded;
});

casper.then(function setIITCOption() {

    casper.echo('Basemap = ' + iitc_basemap, 'INFO');
    casper.echo('Highlight = ' + iitc_highlight, 'INFO');

    this.evaluate(function(base, highlight) {
        window.alert = function(msg) {
            console.log("ALERT: " + msg, 'ERROR')
        }

        var plugins = 'Enabled plugins:\n';
        for (var i in bootPlugins) {
            var info = bootPlugins[i].info;
            if (info) {
                var pname = info.script && info.script.name || info.pluginId;
                if (pname && (pname.substr(0, 13) == 'IITC plugin: ' || pname.substr(0, 13) == 'IITC Plugin: ')) {
                    pname = pname.substr(13);
                }
                var pvers = info.script && info.script.version || info.dateTimeVersion;

                var ptext = pname + ' - ' + pvers;
                if (info.buildName != script_info.buildName) {
                    ptext += ' [' + (info.buildName || 'non-standard plugin') + ']';
                }

                plugins += ptext + '\n';
            } else {
                // no 'info' property of the plugin setup function - old plugin wrapper code
                // could attempt to find the "window.plugin.NAME = function() {};" line it's likely to have..?
                plugins += '<li>(unknown plugin: index ' + i + ')</li>';
            }
        }
        console.log(plugins);

        document.hidden = true;
        var baseLayers = window.layerChooser.getLayers().baseLayers;
        for (var l in baseLayers) {
            if (baseLayers[l].name == base) {
                window.layerChooser.showLayer(baseLayers[l].layerId);
                console.log(baseLayers[l].name + ' enabled');
                break;
            }
        }

        var overlayLayers = window.layerChooser.getLayers().overlayLayers;
        for (var l in overlayLayers) {
            var name = overlayLayers[l].name;
            if (name == 'Portal Levels' || // name == 'DEBUG Data Tiles' ||
                name == 'Drawn Items' || name == 'Cross Links' || name == 'Done Links' ||
                name.indexOf('Player Tracker') >= 0) {
                window.layerChooser.showLayer(overlayLayers[l].layerId);
                console.log(name + ' enabled');
            } else if (name == 'DEBUG Data Tiles') {
                window.layerChooser.showLayer(overlayLayers[l].layerId, false);
                console.log(name + ' disabled');
            }
        }

        var sidebar = $('#scrollwrapper');
        if (sidebar.is(':visible'))
            $('#sidebartoggle').click();

	// highlight high level portals (for targeting)
	window.changePortalHighlights(highlight);

	// turn off extra crap privacy viewer missed
	// we use both in case IITC changes upstream
	$('#privacycontrols').hide();
	$('#chatcontrols, #chat, #chatinput').hide();
	$('#sidebartoggle, #scrollwrapper').hide();
	$('#portal_highlight_select').hide();
	$('.leaflet-control-container').hide();
	$('.leaflet-control').hide();
    }, iitc_basemap, iitc_highlight);
});

function checkStatus() {
    var mapLoaded = casper.page.evaluate(function() {
        var status = window.mapDataRequest.getStatus();

        console.log(status.long + " / " + status.short + " / " + Math.floor(status.progress * 100) + '%');

        return status.short == 'done' || status.short == 'errors' || status.short == 'idle';
    });

    return mapLoaded;
}

var queue = [];
var loading = false;

function capture(options) {
    queue.push(options);

    if (loading) return;
    loading = true;

    setTimeout(processQueue, 100);
}

function processQueue() {
    var cur = queue.shift();
    if (!cur) {
        loading = false;
        return;
    }

    casper.page.evaluate(function(cur) {
        // console.log(JSON.stringify(cur));
        window.idleReset();
        window.map.setView(cur.latlng, cur.zoom);
        // window.mapDataRequest.mapMoveEnd();
        // window.mapDataRequest.setStatus('refreshing');
        window.mapDataRequest.refresh();
    }, cur);

    var step = 0;
    var interval = setInterval(function _check(self) {
        if (checkStatus() || ++step > PAGE_WAIT) {
            clearInterval(interval);

            casper.echo('Processing ' + JSON.stringify(cur), 'INFO');
            var png = casper.captureBase64('png');
            // casper.capture(iitcsnap);

            casper.page.evaluate(function sendImage(cur, png) {
                var res = __utils__.sendAJAX(cur.callback, 'POST',
                    JSON.stringify({
                        image: {
                            base64encoded: png,
                            filename: cur.name + '.png'
                        },
                        echo: 'IITC snapshot of <a href="https://www.ingress.com/intel?ll=' + cur.latlng + '&z=' + cur.zoom + '">' + cur.name + '</a> at ' + new Date
                    }), false, {
                        contentType: 'application/json'
                    });
                console.log('Response: ' + JSON.stringify(res));
            }, cur, png);

            processQueue();
        } else {
            casper.echo('waitng for page to complete ' + step + '/' + PAGE_WAIT, 'INFO');
        }
    }, 2000);

    // we timed out, sigh...
    if (step > PAGE_WAIT) {
	casper.echo('timeout waiting for page to complete', 'ERROR');
	casper.page.evaluate(function sendTimeout(cur) {
                var res = __utils__.sendAJAX(cur.callback, 'POST',
                    JSON.stringify({
			echo: 'IITC snapshot of <a href="https://www.ingress.com/intel?ll=' + cur.latlng + '&z=' + cur.zoom + '">' + cur.name + '</a> at ' + new Date + ': timed out, please retry later'
                    }), false, {
                        contentType: 'application/json'
                    });
                console.log('Response: ' + JSON.stringify(res));
            }, cur);
    }
}

function draw_action(data) {
    casper.page.evaluate(function drawPoly(data) {
        if (data['action'] == 'load') {
            window.prompt = function() {
                return data['json']
            };
            window.plugin.drawTools.optPaste();
        } else if (data['action'] == 'clear') {
            window.confirm = function() {
                return true
            };
            window.plugin.drawTools.optReset()
        }
    }, data);

}

// current time, in minutes
function curtime() {
    return time_in_minutes = Date.now() / MINUTE_IN_MS | 0;
}


casper.run(function() {
    var server = require('webserver').create();
    var	last_command = curtime();

    casper.echo('Starting server at ' + new Date(), 'INFO');

    if (iitc_inactivity_timeout !== undefined) {
	casper.echo('Will shut down after ' + iitc_inactivity_timeout +
		    ' minutes of inactivity.', 'INFO');
	setInterval(function () {
	    if ((curtime() - last_command) > iitc_inactivity_timeout) {
		casper.echo('Shutting down due to inactivity.', 'INFO');
		casper.exit(1);
	    }
	}, MINUTE_IN_MS);
    }

    service = server.listen(31337, function(request, response) {
        try {
	    last_command = curtime();	// reset timeout if enabled
            casper.echo('Request at ' + new Date(), 'INFO');
            // casper.echo(JSON.stringify(request, null, 4));

            var postRaw = (request.postRaw || request.post) + "";
            var data = JSON.parse(postRaw);

            if (data['action']) {
                draw_action(data);
            } else {
                capture(data);
            }

            response.statusCode = 200;
            response.headers = {
                'Cache': 'no-cache',
                'Content-Type': 'text/plain'
            };
            response.write(queue.length);
            response.close();
        } catch (e) {
            casper.echo("" + e, 'ERROR');
            response.statusCode = 500;
            response.write("" + e);
            response.close();
        }
    });
});
