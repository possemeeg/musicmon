#!/usr/bin/env python

import logging
from logging.handlers import RotatingFileHandler
import os
from subprocess import PIPE, CalledProcessError, Popen
import json
import zipfile
import shutil
import sys
from telegram.ext import Updater, CommandHandler, Job
from time import sleep
"""
ffprobe -v error -show_entries stream=sample_fmt,sample_rate -of json  "./Gregorian/The Dark Side/Disc 1 - 06 - Close My Eyes Forever.flac"
ffmpeg -i "$1" -c:a flac -sample_fmt s16 -ar 44100 "${S16}"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
"""

remote_dir = 'pmgpcloud:music/sonos'
recieve_dir = '/var/musicmon/received'
staging_dir = '/var/musicmon/unzipped'
dest_dir = '/mnt/sonos/'
log_file = '/var/log/musicmon.log'

logger = logging.getLogger("musicmon")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(log_file, maxBytes=4096, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(message)s'))
logger.addHandler(handler)

logger.info('Starting up...')

def transcode_newfile(filename, dest_filename):
    logger.info('transcoding {} -> {}'.format(filename, dest_filename))
    command(['ffmpeg', '-i', filename, '-c:a', 'flac', '-sample_fmt', 's16', '-ar', '44100', '-map', '0', '-map', '-V', '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'quiet', dest_filename])

def copy_newfile(filename, dest_filename):
    logger.info('copying {} -> {}'.format(filename, dest_filename))
    shutil.copyfile(filename, dest_filename)

def prep_newfile(filename, dest_filename):
    str_probe = command(['ffprobe','-v','error','-show_entries','stream=sample_fmt,sample_rate','-of','json',filename])
    probe = json.loads(str_probe.decode("utf-8"))
    stream = next(iter([s for s in probe['streams'] if 'sample_fmt' in s and 'sample_rate' in s]), None)

    os.makedirs(os.path.dirname(dest_filename), exist_ok=True)

    if stream is not None and (stream['sample_fmt'] == 's32' or int(stream['sample_rate']) > 44100):
        transcode_newfile(filename, dest_filename)
    else:
        copy_newfile(filename, dest_filename)


def prep_newfiles():
    for root, subdirs, files in os.walk(staging_dir):
        for filename in [os.path.join(root, f) for f in files]:
            dest_filename = os.path.join(dest_dir, filename[filename.index(os.sep, len(staging_dir)) + len(os.sep):])
            logger.info('File {} ->  {}'.format(filename, dest_filename))
            prep_newfile(filename, dest_filename)

def expand_newfiles():
    os.makedirs(staging_dir, exist_ok=True)

    for zipped in [os.path.join(recieve_dir, f) for f in os.listdir(recieve_dir)]:
        logger.info('unzipping {}'.format(zipped))
        try:
            zip_ref = zipfile.ZipFile(zipped, 'r')
            zip_ref.extractall(staging_dir)
            zip_ref.close()
        except zipfile.BadZipFile:
            logger.error('{} is invalid - ignoring'.format(zipped))


def copy_newfiles():
    str_newfiles = command(['rclone', 'lsjson', '{}'.format(remote_dir)])
    newfiles = json.loads(str_newfiles.decode("utf-8"))

    os.makedirs(recieve_dir, exist_ok=True)

    for f in newfiles:
        logger.info('Copying {} from {}'.format(f['Path'], remote_dir))
        lsjson = command(['rclone', 'copy', '{}/{}'.format(remote_dir, f['Path']), recieve_dir])

def cleanup():
    logger.info('Removing interum directories')
    shutil.rmtree(recieve_dir)
    shutil.rmtree(staging_dir)

def newfile_livecycle():
    copy_newfiles()
    expand_newfiles()
    prep_newfiles()
    #cleanup()

def process_newfiles(context):
    logger.info('starting to process new files')
    try:
        newfile_livecycle()

        logger.info('new files processed')
        context.bot.send_message(context.job.context, text='library up to date')
    except Exception as error:
        logger.exception(error)

def command(params):
    try:
        df = Popen(params, stdout=PIPE)
        output, err = df.communicate()
        return output
    except CalledProcessError as e:
        logger.error("Failure running command %s: %s", err, e)
        raise


def newfiles(update, context):
    context.job_queue.run_once(process_newfiles, 0, context=update.message.chat_id)
    update.message.reply_text('roger that')

def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    updater = Updater(sys.argv[1], use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("newfiles", newfiles, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_error_handler(error)

    updater.start_polling()

    updater.idle()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        logger.exception(error)
