#!/usr/bin/env python

import logging
import subprocess
import json
from telegram.ext import Updater, CommandHandler, Job
from time import sleep
"""
ffprobe -v error -show_entries stream=sample_fmt,sample_rate -of json  "./Gregorian/The Dark Side/Disc 1 - 06 - Close My Eyes Forever.flac"
ffmpeg -i "$1" -c:a flac -sample_fmt s16 -ar 44100 "${S16}"
"""
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

source_dir = 'music/sonos'
#source_dir = 'test'

def _process_newfiles():
    lsjson = subprocess.check_output(['rclone', 'lsjson', 'pmgpcloud:{}'.format(source_dir)])
    newfiles = json.loads(lsjson)

    for f in newfiles:
        logger.info('Copying {}'.format(f['Path']))
        lsjson = subprocess.check_output(['rclone', 'copy', 'pmgpcloud:{}/{}'.format(source_dir, f['Path']), '.'])

def process_newfiles(context):
    logger.info('starting to process new files')

    _process_newfiles()

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
    _process_newfiles()
    #main()
