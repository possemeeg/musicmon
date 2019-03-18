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
    def __init__(self, config, logger):
        self.logger = logger
        self.token = config['default']['remote_token']
        self.log_chat_id = config['default']['log_chat_id']
        self.remote_dir = config['default']['remote_dir']
        self.recieve_dir = config['default']['recieve_dir']
        self.staging_dir = config['default']['staging_dir']
        self.dest_dir = config['default']['dest_dir']


    def transcode_newfile(self, filename, dest_filename):
        self.logger.info('transcoding {} -> {}'.format(filename, dest_filename))
        self.command(['ffmpeg', '-i', filename, '-c:a', 'flac', '-sample_fmt', 's16', '-ar', '44100', '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', dest_filename])
    
    def copy_newfile(self, filename, dest_filename):
        self.logger.info('copying {} -> {}'.format(filename, dest_filename))
        shutil.copyfile(filename, dest_filename)
    
    def prep_newfile(self, filename, dest_filename):
        str_probe = self.command(['ffprobe','-v','error','-show_entries','stream=sample_fmt,sample_rate','-of','json',filename])
        probe = json.loads(str_probe)
        stream = next(iter([s for s in probe['streams'] if 'sample_fmt' in s and 'sample_rate' in s]), None)
    
        os.makedirs(os.path.dirname(dest_filename), exist_ok=True)
    
        if stream is not None and (stream['sample_fmt'] == 's32' or int(stream['sample_rate']) > 44100):
            self.transcode_newfile(filename, dest_filename)
        else:
            self.copy_newfile(filename, dest_filename)
    
    
    def prep_newfiles(self):
        for root, subdirs, files in os.walk(staging_dir):
            for filename in [os.path.join(root, f) for f in files]:
                dest_filename = os.path.join(dest_dir, filename[filename.index(os.sep, len(staging_dir)) + len(os.sep):])
                logger.info('File {} ->  {}'.format(filename, dest_filename))
                prep_newfile(filename, dest_filename)
    
    def expand_newfiles(self):
        os.makedirs(staging_dir, exist_ok=True)
    
        for zipped in [os.path.join(recieve_dir, f) for f in os.listdir(recieve_dir)]:
            logger.info('unzipping {}'.format(zipped))
            try:
                zip_ref = zipfile.ZipFile(zipped, 'r')
                zip_ref.extractall(staging_dir)
                zip_ref.close()
            except zipfile.BadZipFile:
                logger.error('{} is invalid - ignoring'.format(zipped))
    
    
    def copy_newfiles(self):
        str_newfiles = command(['rclone', 'lsjson', '{}'.format(remote_dir)])
        newfiles = json.loads(str_newfiles)
    
        os.makedirs(recieve_dir, exist_ok=True)
    
        for f in newfiles:
            logger.info('Copying {} from {}'.format(f['Path'], remote_dir))
            lsjson = command(['rclone', 'copy', '{}/{}'.format(remote_dir, f['Path']), recieve_dir])
    
    def cleanup(self):
        logger.info('Removing interum directories')
        shutil.rmtree(recieve_dir)
        shutil.rmtree(staging_dir)
    
    def newfile_livecycle(self):
        logger.info('Testing only so not doing anything')
        #self.copy_newfiles()
        #self.expand_newfiles()
        #self.prep_newfiles()
        #self.cleanup()
    
    def process_newfiles(self, context):
        logger.info('starting to process new files')
        info = context.bot.send_message(chat_id=self.log_chat_id, text='starting to process new fileslibrary up to date')
        logger.info(info)
        try:
            self.newfile_livecycle()
    
            logger.info('new files processed')
            context.bot.send_message(context.job.context, text='library up to date')
        except Exception as error:
            logger.exception(error)
    
    def command(self, params):
        try:
            df = Popen(params, stdout=PIPE)
            output, err = df.communicate()
            return output.decode("utf-8")
        except CalledProcessError as e:
            logger.error("Failure running command %s: %s", err, e)
            raise
    
    
    def newfiles(self, update, context):
        try:
            logger.info('newfiles command')
            context.job_queue.run_once(self.process_newfiles, 0, context=update.message.chat_id)
            update.message.reply_text('roger that')
        except Exception as error:
            logger.exception(error)
    
    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)
    
    def main(self):
        updater = Updater(self.token, use_context=True)
    
        dp = updater.dispatcher
    
        dp.add_handler(CommandHandler("newfiles", self.newfiles, pass_args=True, pass_job_queue=True, pass_chat_data=True))
        dp.add_error_handler(self.error)
    
        updater.start_polling()
    
        updater.idle()

class ChannelHandler(StreamHandler):
    def __init__(self, chat_id):
        self.chat_id = chat_id

    def emit(self, record):
        msg = self.format(record)

if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read_file(open(sys.argv[1]))
    #config.read_file('/Users/petermetcalf/pmg/musicmon/config.ini')
    logger = logging.getLogger("musicmon")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(config['default']['log_file'], maxBytes=4096, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(message)s'))
    logger.addHandler(handler)
    logger.info('Starting up...')

    try:
        Main(config, logger).main()
    except Exception as error:
        logger.exception(error)
