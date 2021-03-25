/**
https://github.com/cgloeckner/pyvtt/

Copyright (c) 2020-2021 Christian Glöckner
License: MIT (see LICENSE for details)
*/

var gm   = '';
var game = '';

/// Get delta for stepping music volume up or down, based on the current volume
function getMusicVolumeDelta(v) {
    if (v > 0.5) {
        return 0.1
    } else if (v > 0.25) {
        return 0.05;
    } else if (v > 0.1) {
        return 0.03
    } else {
        return 0.01;
    }
}

/// Set the volume to a specific value (also stored in browser, too)
function setMusicVolume(v) {
    var player = $('#audioplayer')[0];    
    player.volume = v;
    localStorage.setItem('volume', v);
}

/// Display music volume or 'OFF'
function showMusicVolume() {
    var player = $('#audioplayer')[0];
    var v = parseInt(player.volume * 100) + '%'
    if (player.paused || player.volume == 0.0) {
        v = 'OFF';
    }
    $('#volume')[0].innerHTML = v;
}

/// Make music one step quieter (may turn it off)
function onQuieterMusic() {
    var player = $('#audioplayer')[0];
    var v = player.volume;
    delta = getMusicVolumeDelta(v);
    v -= delta;
    if (v < 0.01) {
        // stop playback if 0% reached
        v = 0.0;
        player.pause();
    }            
    setMusicVolume(v);
    showMusicVolume();
}

/// Make music one step louder (may turn it on)
function onLouderMusic() {
    var player = $('#audioplayer')[0];
    var v = player.volume;
    delta = getMusicVolumeDelta(v);
    v += delta;
    if (v > 1.0) {
        v = 1.0;
    }
    if (player.paused) {
        // start playback
        player.play()
    }
    setMusicVolume(v);
    showMusicVolume();
}

/// Stop music completly (if game was quit)
function onStopMusic() {   
    var player = $('#audioplayer')[0];
    player.pause();
    showMusicVolume();
}

/// Toggle music playback (if volume percentage is clicked)
function onToggleMusic() { 
    var player = $('#audioplayer')[0];
    
    if (player.paused) {
        if (player.volume == 0.0) {
            onLouderMusic();
            
        } else {
            player.play();
            showMusicVolume();
        }
    } else {
        player.pause();
        showMusicVolume();
    }
}

function refreshStream() { 
    var player = $('#audioplayer')[0];
    
    player.src = '/music/' + gm + '/' + game + '/' + Date.now();
}

function onUpdateMusic() {
    var player = $('#audioplayer')[0];
    var was_paused = player.paused;
    
    refreshStream();
    if (!was_paused) {
        player.play();
    }
}

function onInitMusicPlayer(gmurl, url) {
    // setup default volume
    default_volume = localStorage.getItem('volume');
    if (default_volume == null) {
        default_volume = 0.15;
    }

    // setup audio source
    gm   = gmurl;
    game = url;
    
    var player = $('#audioplayer')[0];
    player.volume = default_volume;
    refreshStream();
}
