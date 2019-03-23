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
import configparser
"""
ffprobe -v error -show_entries stream=sample_fmt,sample_rate -of json  "./Gregorian/The Dark Side/Disc 1 - 06 - Close My Eyes Forever.flac"
ffmpeg -i "$1" -c:a flac -sample_fmt s16 -ar 44100 "${S16}"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

remote_dir = pmgpcloud:music/sonos
recieve_dir = /var/musicmon/received
staging_dir = /var/musicmon/unzipped
dest_dir = /mnt/sonos/
log_file = /var/log/musicmon.log
"""

class Config:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read_file(open(sys.argv[1]))
        self.log_file = config['default']['log_file']
        self.remote_token = config['default']['remote_token']
        self.log_chat_id = config['default']['log_chat_id']
        self.remote_dir = config['default']['remote_dir']
        self.recieve_dir = config['default']['recieve_dir']
        self.staging_dir = config['default']['staging_dir']
        self.dest_dir = config['default']['dest_dir']

class BotLogHandler(logging.StreamHandler):
    def __init__(self, bot, chat_id):
        super(BotLogHandler, self).__init__()
        self.bot = bot
        self.chat_id = chat_id

    def emit(self, record):
        msg = self.format(record)
        self.bot.send_message(chat_id=self.chat_id, text=msg)

    
def run(config):
    logger = logging.getLogger("musicmon")
    handler = RotatingFileHandler(config.log_file, maxBytes=14096, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(message)s'))
    logger.addHandler(handler)
    updater = Updater(config.remote_token, use_context=True)
    bot_handler = BotLogHandler(updater.bot, config.log_chat_id)
    bot_handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(message)s'))
    bot_handler.setLevel(logging.WARNING)
    logger.addHandler(bot_handler)
    logger.setLevel(logging.DEBUG)

    def bot_newfiles(update, context):
        def process_newfiles(context):
            def newfile_lifecycle(context):
                def command(params):
                    try:
                        logger.debug('Command: {}'.format(' '.join(params)))
                        df = Popen(params, stdout=PIPE, stderr=PIPE)
                        output, err = df.communicate()
                        if (err is not None and len(err)):
                            raise Exception("Command failed with error: {}".format(err))
                        return output.decode("utf-8")
                    except CalledProcessError as e:
                        logger.exception(e)
                        raise
                    except Exception as error:
                        logger.exception(error)
                        raise
                def query_newfiles():
                    str_newfiles = command(['rclone', 'lsjson', '{}'.format(config.remote_dir)])
                    return json.loads(str_newfiles)

                def copy_newfiles(context, newfiles):

                    def expand_newfiles(zipped):

                        def prep_newfiles(soundfilelist):

                            def prep_newfile(filename, dest_filename):

                                def transcode_newfile(filename, dest_filename):
                                    logger.info('transcoding {} -> {}'.format(filename, dest_filename))
                                    command(['ffmpeg', '-i', filename, '-c:a', 'flac', '-sample_fmt', 's16', '-ar', '44100',
                                        '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', dest_filename])

                                def copy_newfile(filename, dest_filename):
                                    logger.info('copying {} -> {}'.format(filename, dest_filename))
                                    shutil.copyfile(filename, dest_filename)

                                def try_copy_image(filename, dest_filename):
                                    try:
                                        cover_jpg = os.path.join(os.path.dirname(dest_filename), "folder.jpg")
                                        if not os.path.isfile(cover_jpg):
                                            command(['ffmpeg', '-i', filename, '-an', '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', cover_jpg])
                                    except Exception as error:
                                        logger.debug('An attempt to extract an image from the file failed and is being ignored. {}'.format(error))
        
                                str_probe = command(['ffprobe','-v','error','-show_entries','stream=sample_fmt,sample_rate','-of','json',filename])
                                probe = json.loads(str_probe)
                                stream = next(iter([s for s in probe['streams'] if 'sample_fmt' in s and 'sample_rate' in s]), None) if 'streams' in probe else None
                            
                                os.makedirs(os.path.dirname(dest_filename), exist_ok=True)
                            
                                try_copy_image(filename, dest_filename)

                                if stream is not None and (stream['sample_fmt'] == 's32' or int(stream['sample_rate']) > 44100):
                                    transcode_newfile(filename, dest_filename)
                                else:
                                    copy_newfile(filename, dest_filename)

                                os.remove(filename)

                            def replace_root(filename, old, new):
                                return os.path.join(new, filename[filename.index(os.sep, len(old)) + len(os.sep):])

                            logger.info('prepping new files {}'.format(soundfilelist))
                            for filename in [os.path.join(config.staging_dir, f) for f in soundfilelist]:
                                if os.path.isfile(filename):
                                    dest_filename = replace_root(filename, config.staging_dir, config.dest_dir)
                                    logger.info('File {} -> {}'.format(filename, dest_filename))
                                    prep_newfile(filename, dest_filename)

                        logger.info('Expanding new files')
                        os.makedirs(config.staging_dir, exist_ok=True)
                    
                        logger.info('unzipping {}'.format(zipped))
                        try:
                            zip_ref = zipfile.ZipFile(zipped, 'r')
                            filelist = zip_ref.namelist()
                            zip_ref.extractall(config.staging_dir)
                            zip_ref.close()
                            prep_newfiles(filelist)
                            logger.info('New file {} complete - deleting'.format(zipped))
                        except zipfile.BadZipFile:
                            logger.error('{} invalid zip file - ignoring'.format(zipped))

                    logger.info('Copying new files')
                    os.makedirs(config.recieve_dir, exist_ok=True)
                
                    for f in newfiles:
                        try:
                            logger.info('Copying {} from {}'.format(f['Path'], config.remote_dir))
                            zipped = os.path.join(config.recieve_dir, f['Path'])
                            remote = '{}/{}'.format(config.remote_dir, f['Path'])
                            command(['rclone', 'copy', remote, config.recieve_dir])
                            expand_newfiles(zipped)
                            command(['rclone', 'deletefile', remote])
                            os.remove(zipped)
                            context.bot.send_message(context.job.context, text='{} copied into library'.format(f['Path']))
                        except Exception as error:
                            logger.exception(error)
                            context.bot.send_message(context.job.context, text='👎 - {} failed'.format(f['Path']))

                newfiles = query_newfiles()
                logger.info('new files to process: {}'.format(newfiles))
                copy_newfiles(context, newfiles)

            logger.info('starting to process new files')
            try:
                newfile_lifecycle(context)
                logger.info('new files processed')
                context.bot.send_message(context.job.context, text='library up to date')
                return
            except Exception as error:
                logger.exception(error)
            context.bot.send_message(context.job.context, text='Job failed - please see logs')

        try:
            logger.info('newfiles requested')
            context.job_queue.run_once(process_newfiles, 0, context=update.message.chat_id)
            update.message.reply_text('👍')
            return
        except Exception as error:
            logger.exception(error)
        update.message.reply_text('👎 - Something went wrong')

    def bot_log(update, context):
        update.message.reply_text('👍 - sending log')
        update.message.reply_document(document=open(config.log_file, 'rb'))

    def bot_error(update, context):
        """Log Errors caused by Updates."""
        logger.error('Update "%s" caused error "%s"', update, context.error)

    logger.info('Starting up...')

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("newfiles", bot_newfiles, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_handler(CommandHandler("log", bot_log, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_error_handler(bot_error)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    run(Config())
