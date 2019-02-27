#!/usr/bin/env python3
#
# FFProbe Bitrate Graph
#
# Copyright (c) 2013-2017, Eric Work
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

import sys
import shutil
import argparse
import subprocess

# prefer C-based ElementTree
try:
    import xml.etree.cElementTree as etree
except ImportError:
    import xml.etree.ElementTree as etree

# check for matplot lib
try:
    import numpy
    import matplotlib.pyplot as matplot
except ImportError:
    sys.stderr.write("Error: Missing package 'python3-matplotlib'\n")
    sys.exit(1)

# check for ffprobe in path
if not shutil.which("ffprobe"):
    sys.stderr.write("Error: Missing ffprobe from package 'ffmpeg'\n")
    sys.exit(1)

import os

if not os.environ["DISPLAY"]:
    matplot.switch_backend('Agg')

# get list of supported matplotlib formats
format_list = list(
    matplot.figure().canvas.get_supported_filetypes().keys())
matplot.close()  # destroy test figure

# parse command line arguments
parser = argparse.ArgumentParser(
    description="Graph bitrate for audio/video stream")
parser.add_argument('input', help="input file/stream", metavar="INPUT")

parser.add_argument('-o', '--output', help="output file")
parser.add_argument('-f', '--format', help="output file format",
    choices=format_list)
parser.add_argument('--min', help="set plot minimum (kbps)", type=int)
parser.add_argument('--max', help="set plot maximum (kbps)", type=int)
args = parser.parse_args()

# check if format given w/o output file
if args.format and not args.output:
    sys.stderr.write("Error: Output format requires output file\n")
    sys.exit(1)

# check given y-axis limits
if args.min and args.max and (args.min >= args.max):
    sys.stderr.write("Error: Maximum should be greater than minimum\n")
    sys.exit(1)

bitrate_data = []
frame_count = 0
frame_bitrate = 0
frame_rate = None
frame_time = 0.0

stream_spec = 'V'

# get frame data for the selected stream
with subprocess.Popen(
    ["ffprobe",
        "-show_entries", "frame",
        "-select_streams", stream_spec,
        "-print_format", "xml",
        args.input
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL) as proc_frame:

    # process xml elements as they close
    for event in etree.iterparse(proc_frame.stdout):

        # skip non-frame elements
        node = event[1]
        if node.tag != 'frame':
            continue

        # count number of frames
        frame_count += 1

        # get frame rate only once (assumes non-variable framerate)
        # TODO: use 'pkt_duration_time' each time instead
        if frame_rate is None:
            with subprocess.Popen(
                ["ffprobe",
                    "-show_entries", "stream",
                    "-select_streams", "V",
                    "-print_format", "xml",
                    args.input
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL) as proc_stream:

                # parse stream header xml
                stream_data = etree.parse(proc_stream.stdout)
                stream_elem = stream_data.find('.//stream')

                # compute frame rate from ratio
                frame_rate_ratio = stream_elem.get('avg_frame_rate')
                (dividend, divisor) = frame_rate_ratio.split('/')
                frame_rate = float(dividend) / float(divisor)

        #
        # frame time (x-axis):
        #
        #   ffprobe conveniently reports the frame time position.
        #
        # frame bitrate (y-axis):
        #
        #   ffprobe reports the frame size in bytes. This must first be
        #   converted to kbits which everyone is use to. To get instantaneous
        #   frame bitrate we must consider the frame duration.
        #
        #   bitrate = (kbits / frame) * (frame / sec) = (kbits / sec)
        #

        # collect frame data
        try:
            frame_time = float(node.get('best_effort_timestamp_time'))
        except:
            try:
                frame_time = float(node.get('pkt_pts_time'))
            except:
                if frame_count > 1:
                    frame_time += float(node.get('pkt_duration_time'))       

        frame_bitrate += (float(node.get('pkt_size')) * 8 / 1000)

        if frame_count % frame_rate != 0:
        	continue

        frame = (frame_time, frame_bitrate)
        frame_bitrate = 0

        # append frame to list by type
        bitrate_data.append(frame)

    if frame_bitrate != 0:
    	frame = (frame_time, frame_bitrate)
    	bitrate_data.append(frame)    

    # check if ffprobe was successful
    if frame_count == 0:
        sys.stderr.write("Error: No frame data, failed to execute ffprobe\n")
        sys.exit(1)

# end frame subprocess

# setup new figure
matplot.figure().canvas.set_window_title(args.input)
matplot.title("Stream Bitrate vs Time")
matplot.xlabel("Time (sec)")
matplot.ylabel("Bitrate (kbit/s)")
matplot.grid(True)

global_peak_bitrate = 0.0
global_mean_bitrate = 0.0

# render charts in order of expected decreasing size

# convert list of tuples to numpy 2d array
frame_array = numpy.array(bitrate_data)

# update global peak bitrate
peak_bitrate = frame_array.max(0)[1]
if peak_bitrate > global_peak_bitrate:
    global_peak_bitrate = peak_bitrate

# update global mean bitrate (using piecewise mean)
mean_bitrate = frame_array.mean(0)[1]
global_mean_bitrate += mean_bitrate * (len(bitrate_data) / (frame_count / frame_rate))

bar_width = 1
opacity = 0.65

index = numpy.arange(len(frame_array))

rects = matplot.bar(index + 0.5, frame_array[:,1], bar_width,
                alpha=opacity, color='r')

# set y-axis limits if requested
if args.min:
    matplot.ylim(ymin=args.min)
if args.max:
    matplot.ylim(ymax=args.max)

# calculate peak line position (left 15%, above line)
peak_text_x = matplot.xlim()[1] * 0.15
peak_text_y = global_peak_bitrate + \
    ((matplot.ylim()[1] - matplot.ylim()[0]) * 0.015)
peak_text = "peak ({:.0f})".format(global_peak_bitrate)

# draw peak as think black line w/ text
matplot.axhline(global_peak_bitrate, linewidth=2, color='black')
matplot.text(peak_text_x, peak_text_y, peak_text,
    horizontalalignment='center', fontweight='bold', color='black')

# calculate mean line position (right 85%, above line)
mean_text_x = matplot.xlim()[1] * 0.85
mean_text_y = global_mean_bitrate + \
    ((matplot.ylim()[1] - matplot.ylim()[0]) * 0.015)
mean_text = "mean ({:.0f})".format(global_mean_bitrate)

# draw mean as think black line w/ text
matplot.axhline(global_mean_bitrate, linewidth=2, color='black')
matplot.text(mean_text_x, mean_text_y, mean_text,
    horizontalalignment='center', fontweight='bold', color='black')

# matplot.legend()

# render graph to file (if requested) or screen
if args.output:
    matplot.savefig(args.output, format=args.format)
else:
    matplot.show()

# vim: ai et ts=4 sts=4 sw=4
