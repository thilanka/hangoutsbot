// ==UserScript==
// @id             iitc-plugin-highlight-level-8@discontent
// @name           IITC plugin: highlight level 8 portals
// @category       Highlighter
// @version        0.0.1.20150726.0
// @namespace      https://github.com/jonatkins/ingress-intel-total-conversion
// @description    Highlight Level 8 portals
// @include        https://www.ingress.com/intel*
// @include        http://www.ingress.com/intel*
// @match          https://www.ingress.com/intel*
// @match          http://www.ingress.com/intel*
// @include        https://www.ingress.com/mission/*
// @include        http://www.ingress.com/mission/*
// @match          https://www.ingress.com/mission/*
// @match          http://www.ingress.com/mission/*
// @grant          none
// ==/UserScript==


function wrapper(plugin_info) {
// ensure plugin framework is there, even if iitc is not yet loaded
if(typeof window.plugin !== 'function') window.plugin = function() {};

//END PLUGIN AUTHORS NOTE

// PLUGIN START ////////////////////////////////////////////////////////

// use own namespace for plugin
window.plugin.portalHighlighter8 = function() {};

window.plugin.portalHighlighter8.colorLevel = function(data) {
  var portal_level = data.portal.options.level;

  var opacity = .6;
  if (portal_level >= 8) {
    data.portal.setStyle({fillColor: 'red', fillOpacity: opacity});
  } 
}

var setup =  function() {
  window.addPortalHighlighter('Level 8 Portals', window.plugin.portalHighlighter8.colorLevel);
}

// PLUGIN END //////////////////////////////////////////////////////////


setup.info = plugin_info; //add the script info data to the function as a property
if(!window.bootPlugins) window.bootPlugins = [];
window.bootPlugins.push(setup);
// if IITC has already booted, immediately run the 'setup' function
if(window.iitcLoaded && typeof setup === 'function') setup();
} // wrapper end
// inject code into site context
var script = document.createElement('script');
var info = {};
if (typeof GM_info !== 'undefined' && GM_info && GM_info.script) info.script = { version: GM_info.script.version, name: GM_info.script.name, description: GM_info.script.description };
script.appendChild(document.createTextNode('('+ wrapper +')('+JSON.stringify(info)+');'));
(document.body || document.head || document.documentElement).appendChild(script);


