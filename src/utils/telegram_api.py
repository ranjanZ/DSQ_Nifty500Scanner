import telebot
from telebot import types
import requests
#Conexion con nuestro BOT
from market_scanner import get_stgy_out





TOKEN = '8222892843:AAH6dzw3xTL1vMWqfRKpx2lWjmP8u4xuQRM'
bot = telebot.TeleBot(TOKEN)







@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, 'Hello Ranjan Bot Here')



@bot.message_handler(commands=['help'])
def send_welcome(message):
    bot.reply_to(message, '/get_stocks \n /update')



@bot.message_handler(commands=['get_summary'])
def send_welcome(message):
    bot.reply_to(message,"Please wait|| Scannning Stocks...")
    summary,results=get_stgy_out()

    bot.reply_to(message,str(summary))

    for r in results['Volume_Prddce_Strategy']:   
            bot.reply_to(message,r['name']+" -------   "+r['signal'])


@bot.message_handler(commands=['get_stocks'])
def send_welcome(message):
    bot.reply_to(message,"Please wait|| Scannning Stocks...")
    summary,results=get_stgy_out()
    
    bot.reply_to(message,str(summary))
   
    s=""
    for r in results['Volume_Price_Strategy']:   
            s=s+r['name']+" -------   "+r['signal']+"\n"
    #bot.reply_to(message,r['name']+" -------   "+r['signal'])
    bot.reply_to(message,s)



@bot.message_handler(commands=['update'])
def send_welcome(message):
    from read_data_store_db_lambda1 import update
    bot.reply_to(message,"Please wait || updatting candles...")
    update()
    bot.reply_to(message,"Update Done")


if __name__ == "__main__":
    bot.polling(none_stop=True)



