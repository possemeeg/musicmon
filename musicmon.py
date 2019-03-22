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

class Main:
    def __init__(self, config):
        self.logger = logging.getLogger("musicmon")
        self.log_file = config['default']['log_file']
        handler = RotatingFileHandler(self.log_file, maxBytes=14096, backupCount=2)
        handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(message)s'))
        self.logger.addHandler(handler)
        self.updater = Updater(config['default']['remote_token'], use_context=True)
        bot_handler = BotLogHandler(self.updater.bot, config['default']['log_chat_id'])
        bot_handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(message)s'))
        bot_handler.setLevel(logging.WARNING)
        self.logger.addHandler(bot_handler)
        self.logger.setLevel(logging.DEBUG)

        self.remote_dir = config['default']['remote_dir']
        self.recieve_dir = config['default']['recieve_dir']
        self.staging_dir = config['default']['staging_dir']
        self.dest_dir = config['default']['dest_dir']

    def cleanup(self):
        self.logger.info('Removing interum directories')
        shutil.rmtree(self.recieve_dir)
        shutil.rmtree(self.staging_dir)
    
    def newfile_lifecycle(self, context):
        newfiles = self.query_newfiles()
        self.logger.info('new files to process: {}'.format(newfiles))
        self.copy_newfiles(context, newfiles)
    
    def query_newfiles(self):
        str_newfiles = self.command(['rclone', 'lsjson', '{}'.format(self.remote_dir)])
        return json.loads(str_newfiles)
    
    def copy_newfiles(self, context, newfiles):
        self.logger.info('Copying new files')
        os.makedirs(self.recieve_dir, exist_ok=True)
    
        for f in newfiles:
            try:
                self.logger.info('Copying {} from {}'.format(f['Path'], self.remote_dir))
                zipped = os.path.join(self.recieve_dir, f['Path'])
                remote = '{}/{}'.format(self.remote_dir, f['Path'])
                self.command(['rclone', 'copy', remote, self.recieve_dir])
                self.expand_newfiles(zipped)
                self.command(['rclone', 'deletefile', remote])
                context.bot.send_message(context.job.context, text='{} copied into library'.format(f['Path']))
            except:
                self.logger.error("Unexpected %s", sys.exc_info()[0])
                context.bot.send_message(context.job.context, text='👎 - {} failed'.format(f['Path']))


    def expand_newfiles(self, zipped):
        self.logger.info('Expanding new files')
        os.makedirs(self.staging_dir, exist_ok=True)
    
        self.logger.info('unzipping {}'.format(zipped))
        try:
            zip_ref = zipfile.ZipFile(zipped, 'r')
            filelist = zip_ref.namelist()
            zip_ref.extractall(self.staging_dir)
            zip_ref.close()
            self.prep_newfiles(filelist)
            self.logger.info('New file {} complete - deleting'.format(zipped))
            os.remove(zipped)
        except zipfile.BadZipFile:
            self.logger.error('{} invalid zip file - ignoring'.format(zipped))
            

    def prep_newfiles(self, soundfilelist):
        self.logger.info('prepping new files {}'.format(soundfilelist))
        for filename in [os.path.join(self.staging_dir, f) for f in soundfilelist]:
            if os.path.isfile(filename):
                dest_filename = self.replace_root(filename, self.staging_dir, self.dest_dir)
                self.logger.info('File {} -> {}'.format(filename, dest_filename))
                self.prep_newfile(filename, dest_filename)

    def replace_root(self, filename, old, new):
        return os.path.join(new, filename[filename.index(os.sep, len(old)) + len(os.sep):])
    
    def prep_newfile(self, filename, dest_filename):
        str_probe = self.command(['ffprobe','-v','error','-show_entries','stream=sample_fmt,sample_rate','-of','json',filename])
        probe = json.loads(str_probe)
        stream = next(iter([s for s in probe['streams'] if 'sample_fmt' in s and 'sample_rate' in s]), None) if 'streams' in probe else None
    
        os.makedirs(os.path.dirname(dest_filename), exist_ok=True)
    
        self.try_copy_image(filename, dest_filename)

        if stream is not None and (stream['sample_fmt'] == 's32' or int(stream['sample_rate']) > 44100):
            self.transcode_newfile(filename, dest_filename)
        else:
            self.copy_newfile(filename, dest_filename)

        os.remove(filename)
    
    def try_copy_image(self, filename, dest_filename):
        try:
            cover_jpg = os.path.join(os.path.dirname(dest_filename), "folder.jpg")
            if not os.path.isfile(cover_jpg):
                self.command(['ffmpeg', '-i', filename, '-an', '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', cover_jpg])
        except:
            logger.debug('An attempt to extract an image from the file failed and is being ignored')

    def transcode_newfile(self, filename, dest_filename):
        self.logger.info('transcoding {} -> {}'.format(filename, dest_filename))
        self.command(['ffmpeg', '-i', filename, '-c:a', 'flac', '-sample_fmt', 's16', '-ar', '44100', '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', dest_filename])
    
    def copy_newfile(self, filename, dest_filename):
        self.logger.info('copying {} -> {}'.format(filename, dest_filename))
        shutil.copyfile(filename, dest_filename)
    
    def process_newfiles(self, context):
        self.logger.info('starting to process new files')
        try:
            self.newfile_lifecycle(context)
            self.logger.info('new files processed')
            context.bot.send_message(context.job.context, text='library up to date')
            return
        except Exception as error:
            self.logger.exception(error)
        except:
            self.logger.error("Unexpected %s", sys.exc_info()[0])
        context.bot.send_message(context.job.context, text='Job failed - please see logs')
    
    def command(self, params):
        try:
            self.logger.debug('Command: {}'.format(' '.join(params)))
            df = Popen(params, stdout=PIPE, stderr=PIPE)
            output, err = df.communicate()
            if (err is not None and len(err)):
                self.logger.error(err)
                raise Exception("Command failed")
            return output.decode("utf-8")
        except CalledProcessError as e:
            self.logger.error("Failure running command %s", e)
            raise
        except Exception as error:
            self.logger.exception(error)
            raise
        except:
            self.logger.error("Unexpected %s", sys.exc_info()[0])
            raise
    
    
    def newfiles(self, update, context):
        try:
            self.logger.info('newfiles command')
            context.job_queue.run_once(self.process_newfiles, 0, context=update.message.chat_id)
            update.message.reply_text('👍')
            return
        except Exception as error:
            self.logger.exception(error)
        except:
            self.logger.error("Unexpected %s", sys.exc_info()[0])
        update.message.reply_text('👎 - Something went wrong')
    
    def log(self, update, context):
        update.message.reply_text('👍 - sending log')
        update.message.reply_document(document=open(self.log_file, 'rb'))

    def error(self, update, context):
        """Log Errors caused by Updates."""
        self.logger.warning('Update "%s" caused error "%s"', update, context.error)

    def run(self):
        self.logger.info('Starting up...')

        dp = self.updater.dispatcher
        dp.add_handler(CommandHandler("newfiles", self.newfiles, pass_args=True, pass_job_queue=True, pass_chat_data=True))
        dp.add_handler(CommandHandler("log", self.log, pass_args=True, pass_job_queue=True, pass_chat_data=True))
        dp.add_error_handler(self.error)
        self.updater.start_polling()
        self.updater.idle()

    def main(self):
        try:
            self.run()
        except Exception as error:
            self.logger.exception(error)
        except:
            self.logger.error("Unexpected %s", sys.exc_info()[0])


class BotLogHandler(logging.StreamHandler):
    def __init__(self, bot, chat_id):
        super(BotLogHandler, self).__init__()
        self.bot = bot
        self.chat_id = chat_id

    def emit(self, record):
        msg = self.format(record)
        self.bot.send_message(chat_id=self.chat_id, text=msg)

if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read_file(open(sys.argv[1]))
    Main(config).main()
