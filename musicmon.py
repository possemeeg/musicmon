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
import pylast
import urllib3
from PIL import Image

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
        self.last_key = config['default']['last_key']
        self.last_secret = config['default']['last_secret']
        self.last_user = config['default']['last_user']
        self.last_password_hash = config['default']['last_password_hash']

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

    class ImageProvider:
        def __init__(self):
            self.lastfm_network = pylast.LastFMNetwork(
                api_key=config.last_key,
                api_secret=config.last_secret,
                username=config.last_user,
                password_hash=config.last_password_hash,
            )
            self.http = urllib3.PoolManager()

        def download_image(self, artist, album, image_path):
            last_album = self.lastfm_network.get_album(artist, album)
            png_path = '{}.png'.format(image_path)
            with self.http.request('GET', last_album.get_cover_image(), preload_content=False) as r, open(png_path, 'wb') as out_file:       
                shutil.copyfileobj(r, out_file)
            try:
                Image.open(png_path).convert('RGB').save(image_path, "JPEG")
            except:
                os.remove(image_path)
                raise
            finally:
                os.remove(png_path)

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
                def command_json(params):
                    return json.loads(command(params))

                def query_newfiles():
                    return command_json(['rclone', 'lsjson', '{}'.format(config.remote_dir)])

                def copy_newfiles(context, newfiles):
                    def expand_newfiles(zipped):
                        def prep_newfiles(soundfilelist):
                            def prep_newfile(filename, dest_filename):
                                def transcode_newfile():
                                    logger.info('transcoding {} -> {}'.format(filename, dest_filename))
                                    command(['ffmpeg', '-i', filename, '-c:a', 'flac', '-sample_fmt', 's16', '-ar', '44100',
                                        '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', dest_filename])

                                def copy_newfile():
                                    logger.info('copying {} -> {}'.format(filename, dest_filename))
                                    shutil.copyfile(filename, dest_filename)

                                def try_copy_image():
                                    cover_jpg = os.path.join(os.path.dirname(dest_filename), "folder.jpg")
                                    def extract():
                                        command(['ffmpeg', '-i', filename, '-an', '-y', '-nostats', '-hide_banner', '-vsync', '2', '-loglevel', 'error', '-nostdin', cover_jpg])

                                    def download():
                                        probe = command_json(['ffprobe','-v','error','-show_entries','format_tags=artist,album','-of','json',filename])
                                        ImageProvider().download_image(probe['format']['tags']['ARTIST'], probe['format']['tags']['ALBUM'], cover_jpg)

                                    for method in {extract, download}:
                                        if os.path.isfile(cover_jpg):
                                            return
                                        try:
                                            method()
                                        except Exception as error:
                                            logger.debug('An attempt to extract an image from the file failed and is being ignored. {}'.format(error))
    

                                probe = command_json(['ffprobe','-v','error','-show_entries','stream=sample_fmt,sample_rate','-of','json',filename])
                                stream = next(iter([s for s in probe['streams'] if 'sample_fmt' in s and 'sample_rate' in s]), None) if 'streams' in probe else None
                            
                                os.makedirs(os.path.dirname(dest_filename), exist_ok=True)
                            
                                try_copy_image()

                                if stream is not None and (stream['sample_fmt'] == 's32' or int(stream['sample_rate']) > 44100):
                                    transcode_newfile()
                                else:
                                    copy_newfile()

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
                            context.bot.send_message(context.job.context, text='🙂 - {} copied into library'.format(f['Path']))
                        except Exception as error:
                            logger.exception(error)
                            context.bot.send_message(context.job.context, text='😢 - {} failed'.format(f['Path']))

                newfiles = query_newfiles()
                logger.info('new files to process: {}'.format(newfiles))
                copy_newfiles(context, newfiles)

            logger.info('starting to process new files')
            try:
                newfile_lifecycle(context)
                logger.info('new files processed')
                context.bot.send_message(context.job.context, text='🙂 - library up to date')
                return
            except Exception as error:
                logger.exception(error)
            context.bot.send_message(context.job.context, text='😢 - Job failed')

        try:
            logger.info('newfiles requested')
            context.job_queue.run_once(process_newfiles, 0, context=update.message.chat_id)
            update.message.reply_text('👍 - processing files')
            return
        except Exception as error:
            logger.exception(error)
        update.message.reply_text('😢 - Something went wrong')

    def bot_log(update, context):
        update.message.reply_text('👍 - sending log')
        update.message.reply_document(document=open(config.log_file, 'rb'))

    def bot_status(update, context):
        update.message.reply_text('👍')

    def bot_error(update, context):
        """Log Errors caused by Updates."""
        logger.error('Update "%s" caused error "%s"', update, context.error)

    logger.info('Starting up...')

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("newfiles", bot_newfiles, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_handler(CommandHandler("log", bot_log, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_handler(CommandHandler("status", bot_status, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_error_handler(bot_error)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    run(Config())
