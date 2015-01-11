#!/usr/bin/env python
# Pirate Radio
# Author: Wynter Woods (Make Magazine)

import os
import sys
import subprocess
try:
    import configparser
except:
    import ConfigParser as configparser
import re
import random
import threading
import time
import signal
import RPi.GPIO as gpio


fm_process = None
on_off = ["off", "on"]
config_location = "/pirateradio/pirateradio.conf"

frequency = 87.9
shuffle = False
repeat_all = False
merge_audio_in = False
play_stereo = True
music_dir = "/pirateradio"

music_pipe_r, music_pipe_w = os.pipe()
microphone_pipe_r, microphone_pipe_w = os.pipe()


def main():
    daemonize()
    print("To stop run 'kill -15 {0}'".format(os.getpid()))
    setup()
    files = build_file_list()
    if repeat_all:
        while(True):
            play_songs(files)
    else:
        play_songs(files)
    return 0


def build_file_list():
    file_list = []
    for root, folders, files in os.walk(music_dir):
        folders.sort()
        files.sort()
        for filename in files:
            if re.search(".(aac|mp3|wav|flac|m4a|ogg|pls|m3u)$",
                         filename) is not None:
                file_list.append(os.path.join(root, filename))
    return file_list


def play_songs(file_list):
    print("Playing songs to frequency {0}".format(str(frequency)))
    print("Shuffle is " + on_off[shuffle])
    print("Repeat All is " + on_off[repeat_all])
    # print("Stereo playback is " + on_off[play_stereo])

    if shuffle:
        random.shuffle(file_list)
    with open(os.devnull, "w") as dev_null:
        for filename in file_list:
            print("Playing {0}".format(filename))
            global ffmpeg
            if re.search(".pls$", filename) is not None:
                streamurl = parse_pls(filename, 1)
                if streamurl is not None:
                    print("streaming radio from " + streamurl)
                    ffmpeg = subprocess.Popen(["ffmpeg", "-i", streamurl, "-f",
                                               "s16le", "-acodec", "pcm_s16le",
                                               "-ar", "44100", "-ac",
                                               "2" if play_stereo else "1",
                                               "-"], stdout=music_pipe_w,
                                              stderr=dev_null)
            elif re.search(".m3u$", filename) is not None:
                streamurl = parse_m3u(filename, 1)
                if streamurl is not None:
                    print("streaming radio from " + streamurl)
                    ffmpeg = subprocess.Popen(["ffmpeg", "-i", streamurl, "-f",
                                               "s16le", "-acodec", "pcm_s16le",
                                               "-ar", "44100", "-ac",
                                               "2" if play_stereo else "1",
                                               "-"], stdout=music_pipe_w,
                                              stderr=dev_null)
            else:
                ffmpeg = subprocess.Popen(["ffmpeg", "-i", filename, "-f",
                                           "s16le", "-acodec", "pcm_s16le",
                                           "-ac", "2" if play_stereo else "1",
                                           "-ar", "44100", "-"],
                                          stdout=music_pipe_w, stderr=dev_null)
            ffmpeg.wait()


def read_config():
    global frequency
    global shuffle
    global repeat_all
    global play_stereo
    global music_dir
    try:
        config = configparser.ConfigParser()
        config.read(config_location)

    except:
        print("Error reading from config file.")
    else:
        # This resembles the fallback argument, not present in python 2
        try:
            play_stereo = config.get("pirateradio", 'stereo_playback')
        except:
            pass
        try:
            frequency = config.get("pirateradio", 'frequency')
        except:
            pass
        try:
            shuffle = config.getboolean("pirateradio", 'shuffle')
        except:
            pass
        try:
            repeat_all = config.getboolean("pirateradio", 'repeat_all')
        except:
            pass
        try:
            music_dir = config.get("pirateradio", 'music_dir')
        except:
            pass


def parse_pls(src, titleindex):
    # breaking up the pls file in separate strings
    lines = []
    with open(src, "r") as f:
        lines = f.readlines()

    # and parse the lines
    if lines is not None:
        for line in lines:
            # search for the URI
            match = re.match("^[ \\t]*file" + str(titleindex) +
                             "[ \\t]*=[ \\t]*(.*$)", line, flags=re.IGNORECASE)
            if match is not None:
                if match.group(1) is not None:
                    # URI found, it's saved in the second match group
                    # output the URI to the destination file
                    return match.group(1)

    return None


def parse_m3u(src, titleindex):
    # create a list of strings, one per line in the source file
    lines = []
    searchindex = int(1)
    with open(src, "r") as f:
        lines = f.readlines()

    if lines is not None:
        for line in lines:
            # search for the URI
            if '://' in line:
                if searchindex == titleindex:
                    return line
                else:
                    searchindex += 1

    return None


def daemonize():
    fpid = os.fork()
    if fpid != 0:
        sys.exit(0)


def setup():
    # threading.Thread(target = open_microphone).start()

    global frequency
    read_config()
    # open_microphone()
    run_pifm()


def run_pifm(use_audio_in=False):
    global fm_process
    with open(os.devnull, "w") as dev_null:
        fm_process = subprocess.Popen(["/root/pifm", "-", str(frequency),
                                       "44100", "stereo" if play_stereo
                                       else "mono"], stdin=music_pipe_r,
                                      stdout=dev_null)

        # if use_audio_in == False:
        # else:
        #   fm_process = subprocess.Popen(["/root/pifm2", "-", str(frequency),
        #                                  "44100"], stdin=microphone_pipe_r,
        #                                 stdout=dev_null)


def record_audio_input():
    return subprocess.Popen(["arecord", "-fS16_LE", "--buffer-time=50000",
                             "-r", "44100", "-Dplughw:1,0", "-"],
                            stdout=microphone_pipe_w)


def open_microphone():
    global fm_process
    audio_process = None
    if os.path.exists("/proc/asound/card1"):
        audio_process = record_audio_input()
        run_pifm(merge_audio_in)
    else:
        run_pifm()


def terminate(signum, frame):
    # This will stop the transmission not just silencing it
    gpio.setmode(gpio.BOARD)
    gpio.setwarnings(False)
    gpio.setup(7, gpio.OUT)
    gpio.cleanup()

    fm_process.terminate()  # Stop pifm
    ffmpeg.kill()  # Stop ffmpeg. Terminate() didn't always work
    sys.exit()


signal.signal(signal.SIGTERM, terminate)
main()
