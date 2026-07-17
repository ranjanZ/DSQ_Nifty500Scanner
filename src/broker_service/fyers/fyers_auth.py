"""
Fyers Authentication Utility
Generate access token using client_id, secret_key, and TOTP
Reference: Working auth flow from fyers_broker_impl.py test code
"""

import os
import sys
import json
import base64
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from fyers_apiv3 import fyersModel
    FYERS_SDK_AVAILABLE = True
except ImportError as e:
    print(f"❌ Fyers SDK not installed: {e}")
    print("Install it with: pip install fyers")
    FYERS_SDK_AVAILABLE = False
    fyersModel = None

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


def getEncodedString(string):
    """Encode string to base64"""
    string = str(string)
    base64_bytes = base64.b64encode(string.encode("ascii"))
    return base64_bytes.decode("ascii")


def generate_access_token(client_id, secret_key, fyers_id, pin, totp_token, redirect_uri="https://www.google.com"):
    """
    Generate Fyers access token using TOTP
    
    Reference implementation based on working code from fyers_broker_impl.py test
    
    Args:
        client_id: Fyers client ID (e.g., "8ZU1YKGMVT-200")
        secret_key: Fyers secret key
        fyers_id: Fyers user ID (e.g., "YC00531")
        pin: Fyers PIN
        totp_token: TOTP token from Fyers
        redirect_uri: Redirect URI configured in Fyers

    Returns:
        dict: Response containing access_token or error message
    """
    if not FYERS_SDK_AVAILABLE:
        return {"success": False, "error": "Fyers SDK not installed"}
    
    if not REQUESTS_AVAILABLE:
        return {"success": False, "error": "requests library not available"}

    try:
        print(f"🔄 Generating auth token for client_id: {client_id}")

        # Step 1: Create session model to generate initial authcode URL
        session = fyersModel.SessionModel(
            client_id=client_id,
            secret_key=secret_key, 
            redirect_uri=redirect_uri, 
            response_type="code", 
            grant_type="authorization_code"
        )

        # This generates the auth URL but we don't use it directly
        # We need to go through the login flow to get the actual auth code
        auth_url = session.generate_authcode()
        print(f"📝 Initial auth URL generated")

        # Step 2: Send login OTP request
        URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
        res = requests.post(
            url=URL_SEND_LOGIN_OTP, 
            json={"fy_id": getEncodedString(fyers_id), "app_id": "2"},
            timeout=30
        ).json()
        
        if res.get('s') != 'ok':
            return {"success": False, "error": f"Failed to send login OTP: {res}"}
        
        request_key = res.get("request_key")
        if not request_key:
            return {"success": False, "error": "No request_key in OTP response"}
        
        print(f"📝 Login OTP sent successfully")

        # Wait for TOTP to be valid (avoid edge case near 30-second boundary)
        if datetime.now().second % 30 > 27:
            time.sleep(5)

        # Step 3: Verify OTP using TOTP
        URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
        current_totp = pyotp.TOTP(totp_token).now() if PYOTP_AVAILABLE else totp_token
        print(f"🔑 Using TOTP: {current_totp}")
        
        res2 = requests.post(
            url=URL_VERIFY_OTP, 
            json={"request_key": request_key, "otp": current_totp},
            timeout=30
        ).json()
        
        if res2.get('s') != 'ok':
            return {"success": False, "error": f"Failed to verify OTP: {res2}"}
        
        request_key2 = res2.get("request_key")
        if not request_key2:
            return {"success": False, "error": "No request_key in OTP verify response"}
        
        print(f"📝 OTP verified successfully")

        # Step 4: Verify PIN
        ses = requests.Session()
        URL_VERIFY_PIN = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
        payload2 = {
            "request_key": request_key2,
            "identity_type": "pin",
            "identifier": getEncodedString(pin)
        }
        res3 = ses.post(url=URL_VERIFY_PIN, json=payload2, timeout=30).json()
        
        if res3.get('s') != 'ok':
            return {"success": False, "error": f"Failed to verify PIN: {res3}"}
        
        access_token_bearer = res3.get('data', {}).get('access_token')
        if not access_token_bearer:
            return {"success": False, "error": "No access_token in PIN verify response"}
        
        # Set authorization header for next request
        ses.headers.update({
            'authorization': f"Bearer {access_token_bearer}"
        })
        
        print(f"📝 PIN verified successfully")

        # Step 5: Get auth code from token endpoint
        TOKEN_URL = "https://api-t1.fyers.in/api/v3/token"
        payload3 = {
            "fyers_id": fyers_id,
            "app_id": client_id.split('-')[0],  # Extract part before dash
            "redirect_uri": redirect_uri,
            "appType": "200",
            "code_challenge": "",
            "state": "None",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True
        }
        
        res4 = ses.post(url=TOKEN_URL, json=payload3, timeout=30).json()
        
        if res4.get('s') != 'ok':
            return {"success": False, "error": f"Failed to get token URL: {res4}"}
        
        url = res4.get('Url')
        if not url:
            return {"success": False, "error": "No Url in token response"}
        
        # Parse the URL to extract auth_code
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        auth_code = query_params.get('auth_code', [None])[0]
        
        if not auth_code:
            return {"success": False, "error": "No auth_code in redirect URL"}
        
        print(f"✅ Auth code obtained successfully")

        # Step 6: Exchange auth code for access token using SDK
        session.set_token(auth_code)
        token_response = session.generate_token()
        
        print(f"📝 Token response status: {token_response.get('s')}")

        if token_response.get('s') != 'ok':
            return {
                "success": False,
                "error": f"Token generation failed: {token_response}"
            }

        access_token = token_response.get('access_token')
        if not access_token:
            return {
                "success": False,
                "error": "No access_token in response"
            }

        # The access_token format is typically: "client_id:access_token_string"
        print(f"\n✅ SUCCESS! Access Token Generated:")
        print(f"   Full token: {access_token}")

        # Extract just the token part (after the colon) if present
        if ':' in access_token:
            token_parts = access_token.split(':')
            if len(token_parts) == 2:
                token_only = token_parts[1]
                print(f"   Token only: {token_only}")

        return {
            "success": True,
            "access_token": access_token,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        import traceback
        print(f"❌ Error generating token: {traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e)
        }


def save_token_to_env(access_token, env_file_path=".env"):
    """Save access token to .env file"""
    try:
        # Read existing .env file if it exists
        env_content = ""
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as f:
                env_content = f.read()

        # Remove existing FYERS_ACCESS_TOKEN line if present
        lines = env_content.split('\n')
        new_lines = [line for line in lines if not line.startswith('FYERS_ACCESS_TOKEN=')]

        # Add new token
        new_lines.append(f'FYERS_ACCESS_TOKEN={access_token}')

        # Write back
        with open(env_file_path, 'w') as f:
            f.write('\n'.join(new_lines))

        print(f"✅ Token saved to {env_file_path}")
        return True
    except Exception as e:
        print(f"❌ Error saving token: {e}")
        return False


def main():
    """Main function to generate token"""
    print("=" * 60)
    print("FYERS ACCESS TOKEN GENERATOR")
    print("=" * 60)

    if not FYERS_SDK_AVAILABLE:
        print("\n❌ Fyers SDK is not installed.")
        print("   Install it with: pip install fyers")
        sys.exit(1)

    # Default credentials (can be overridden by environment variables)
    client_id = os.getenv('FYERS_CLIENT_ID', '8ZU1YKGMVT-100')
    secret_key = os.getenv('FYERS_SECRET_KEY', 'c9YkxN1yj5TEnz1p')
    fyers_id = os.getenv('FYERS_ID', 'YC00531')
    pin = os.getenv('FYERS_PIN', '1234')
    totp_token = os.getenv('FYERS_TOTP_TOKEN', 'Y3VGJV7N553V5XU6LHWG4ANV67UVTLVP')
    redirect_uri = os.getenv('FYERS_REDIRECT_URI', 'https://www.google.com')

    print(f"\n📋 Configuration:")
    print(f"   Client ID: {client_id}")
    print(f"   Fyers ID: {fyers_id}")
    print(f"   PIN: {'*' * len(pin)}")
    print(f"   TOTP Token: {totp_token[:10]}...")
    print(f"   Redirect URI: {redirect_uri}")

    print(f"\n🔄 Generating access token...")
    result = generate_access_token(
        client_id=client_id,
        secret_key=secret_key,
        fyers_id=fyers_id,
        pin=pin,
        totp_token=totp_token,
        redirect_uri=redirect_uri
    )

    if result.get('success'):
        access_token = result['access_token']
        print(f"\n✅ Token generated successfully!")

        # Ask if user wants to save to .env
        save_choice = input("\n💾 Save token to .env file? (y/n): ").strip().lower()
        if save_choice == 'y':
            save_token_to_env(access_token)
            print(f"\n📝 Remember to restart your application to load the new token!")

        print(f"\n🔑 Your Access Token:")
        print(f"   {access_token}")
        print(f"\n   Or set environment variable:")
        print(f"   export FYERS_ACCESS_TOKEN={access_token}")

    else:
        print(f"\n❌ Failed to generate token:")
        print(f"   Error: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()