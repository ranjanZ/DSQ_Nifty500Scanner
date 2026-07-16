from fyers_apiv3 import fyersModel
import json
import requests
import pyotp
import sys,os,time
import pandas as pd
import datetime
import hashlib
from fyers_apiv3 import fyersModel
import base64
import requests
from urllib.parse import parse_qs,urlparse
from time import sleep
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

################
"""
client_id="96O1TQ69L0-100"
secret_key="IQ9NUYDZ4X"
#redirect_uri="https://trade.fyers.in/api-login/redirect-uri/index.html"
redirect_uri="https://www.google.com"
#redirect_uri="https://127.0.0.1:5000/"
response_type = "code"  
grant_type = "authorization_code"  
state = "sample_state"
fyers_id="XA71982"
pin="1234"
totp_token="A2YB2RMZUEBXOJU5VQ6QKPEX6F7IMQP5"
"""


#client_id="27IH6OKCVZ-100"
#secret_key="OV2B621AGP"

client_id=os.getenv("FYERS_CLIENT_ID", "8ZU1YKGMVT-200")
secret_key=os.getenv("FYERS_SECRET_KEY", "c9YkxN1yj5TEnz1p")
#redirect_uri="https://trade.fyers.in/api-login/redirect-uri/index.html"
redirect_uri=os.getenv("FYERS_REDIRECT_URI", "https://www.google.com")
#redirect_uri="https://127.0.0.1:5000/"
response_type = os.getenv("FYERS_RESPONSE_TYPE", "code")
grant_type = os.getenv("FYERS_GRANT_TYPE", "authorization_code")
state = os.getenv("FYERS_STATE", "sample_state")
fyers_id=os.getenv("FYERS_ID", "YC00531")
pin=os.getenv("FYERS_PIN", "1234")
totp_token=os.getenv("FYERS_TOTP_TOKEN", "Y3VGJV7N553V5XU6LHWG4ANV67UVTLVP")
#"""


"""
appSession = fyersModel.SessionModel(client_id = client_id, redirect_uri = redirect_uri,response_type=response_type,state=state,secret_key=secret_key,grant_type=grant_type)
generateTokenUrl = appSession.generate_authcode()
#open the generateTokenUrl in  browser to active
"""


######################################################

session = fyersModel.SessionModel(
    client_id=client_id,
    secret_key=secret_key, 
    redirect_uri=redirect_uri, 
    response_type=response_type, 
    grant_type=grant_type
)


response = session.generate_authcode()
#########################################################
print("INFO: Getting auth code  for Fyers")

def getEncodedString(string):
    string = str(string)
    base64_bytes = base64.b64encode(string.encode("ascii"))
    return base64_bytes.decode("ascii")
  



URL_SEND_LOGIN_OTP="https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
res = requests.post(url=URL_SEND_LOGIN_OTP, json={"fy_id":getEncodedString(fyers_id),"app_id":"2"}).json()   
#print(res) 

if datetime.datetime.now().second % 30 > 27 : sleep(5)
URL_VERIFY_OTP="https://api-t2.fyers.in/vagator/v2/verify_otp"
res2 = requests.post(url=URL_VERIFY_OTP, json= {"request_key":res["request_key"],"otp":pyotp.TOTP(totp_token).now()}).json()  
#print(res2) 


ses = requests.Session()
URL_VERIFY_OTP2="https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
payload2 = {"request_key": res2["request_key"],"identity_type":"pin","identifier":getEncodedString(pin)}
res3 = ses.post(url=URL_VERIFY_OTP2, json= payload2).json()  
#print(res3) 


ses.headers.update({
    'authorization': f"Bearer {res3['data']['access_token']}"
})


TOKENURL="https://api-t1.fyers.in/api/v3/token"
payload3 = {"fyers_id":fyers_id,
           "app_id":client_id[:-4],
           "redirect_uri":redirect_uri,
           "appType":"200","code_challenge":"",
           "state":"None","scope":"","nonce":"","response_type":"code","create_cookie":True}

res3 = ses.post(url=TOKENURL, json= payload3).json()  
#print(res3)


url = res3['Url']
#print(url)
parsed = urlparse(url)
auth_code = parse_qs(parsed.query)['auth_code'][0]






##########################
print("INFO: generating  fyers token")

session.set_token(auth_code)
response = session.generate_token()

access_token=response["access_token"]
cur_path=os.path.dirname(os.path.abspath(__file__))
fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path=cur_path+"/logs/")


