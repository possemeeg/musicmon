#!/usr/bin/env python

import logging
import os
import subprocess
import json
import zipfile
from telegram.ext import Updater, CommandHandler, Job
from time import sleep
"""
ffprobe -v error -show_entries stream=sample_fmt,sample_rate -of json  "./Gregorian/The Dark Side/Disc 1 - 06 - Close My Eyes Forever.flac"
ffmpeg -i "$1" -c:a flac -sample_fmt s16 -ar 44100 "${S16}"
"""
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

remote_dir = 'pmgpcloud:music/sonos'
recieve_dir = 'received'
staging_dir = 'unzipped'
dest_dir = 'sonos'

def prep_newfile(filename):
    logger.info('processing {}'.format(filename))
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=sample_fmt,sample_rate','-of','json',filename]))
    logger.info('probe {}'.format(probe))
    stream = next(iter([s for s in probe['streams'] if 'sample_fmt' in s and 'sample_rate' in s]), None)
    if stream is None:
        logger.info('file {} does not contain audio'.format(filename))
        return

    #logger.info('stream {}'.format(stream)
    #
    #logger.info('file {} has sample format {} amd rate {}'.format(filename, probe['streams'][0]['sample_fmt'], probe['streams'][0]['sample_rate']))

    #if probe['streams'][0]['sample_fmt'] == 's32' or int(probe['streams'][0]['sample_rate']) > 44100:
    #    logger.info('transcoding {}'.format(filename))
    #else:
    #    logger.info('file {} is suitable for sonos'.format(filename))



def prep_newfiles():
    for root, subdirs, files in os.walk(staging_dir):
        for filename in [os.path.join(root, f) for f in files]:
            prep_newfile(filename)

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
    newfiles = json.loads(subprocess.check_output(['rclone', 'lsjson', '{}'.format(remote_dir)]))

    os.makedirs(recieve_dir, exist_ok=True)

    for f in newfiles:
        logger.info('Copying {}'.format(f['Path']))
        lsjson = subprocess.check_output(['rclone', 'copy', '{}/{}'.format(remote_dir, f['Path']), recieve_dir])

def process_newfiles(context):
    logger.info('starting to process new files')

    copy_newfiles()
    expand_newfiles()
    prep_newfiles()

    logger.info('new files processed')
    context.bot.send_message(context.job.context, text='library up to date')

def newfiles(update, context):
    context.job_queue.run_once(process_newfiles, 0, context=update.message.chat_id)
    update.message.reply_text('roger that')

def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    updater = Updater("<token>", use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("newfiles", newfiles, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_error_handler(error)

    updater.start_polling()

    updater.idle()

if __name__ == '__main__':
    prep_newfiles()
    #main()
