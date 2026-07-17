"""
Fyers Authentication Utility
Generate access token using client_id, secret_key, and TOTP
"""

import os
import sys
import json
from datetime import datetime

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


def generate_access_token(client_id, secret_key, fyers_id, pin, totp_token, redirect_uri="https://www.google.com"):
    """
    Generate Fyers access token using TOTP

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

    try:
        print(f"🔄 Generating auth token for client_id: {client_id}")

        # Generate current TOTP code
        if PYOTP_AVAILABLE:
            totp = pyotp.TOTP(totp_token)
            current_totp = totp.now()
        else:
            # Fallback: use the provided totp_token directly if it's already a code
            current_totp = totp_token

        print(f"🔑 Using TOTP: {current_totp}")

        # Step 1: Create session model with credentials
        session = fyersModel.SessionModel(
            client_id=client_id,
            secret_key=secret_key,
            redirect_uri=redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )

        # Generate authorization URL and extract parameters needed for API call
        auth_url = session.generate_authcode()
        print(f"📝 Auth URL: {auth_url}")

        # Step 2: Make direct API call to generate auth code with TOTP
        import requests
        auth_api_url = "https://api-t1.fyers.in/api/v3/generate-authcode"
        auth_payload = {
            "fy_id": fyers_id,
            "app_id": client_id.split('-')[0],  # Extract part before dash
            "app_type": "web",
            "redirect_uri": redirect_uri,
            "state": "sample_state",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True,
            "password": pin,
            "totp": current_totp
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post(auth_api_url, json=auth_payload, headers=headers, timeout=30)

        print(f"📝 Auth code API response status: {response.status_code}")

        if response.status_code != 200:
            error_text = response.text[:500] if response.text else "No response text"
            # Detect Cloudflare blocking
            if response.status_code == 403 or '<!DOCTYPE html>' in response.text or 'Cloudflare' in response.text:
                error_text = "CLOUDBLOCK: Fyers auth API is blocked by Cloudflare (403). This is common from cloud/server IPs. Generate token locally instead."
            return {
                "success": False,
                "error": f"Auth API returned status {response.status_code}: {error_text}"
            }

        auth_code_response = response.json()
        print(f"📝 Auth code response: {json.dumps(auth_code_response, indent=2)}")

        if auth_code_response.get('s') != 'ok':
            return {
                "success": False,
                "error": f"Auth code generation failed: {auth_code_response}"
            }

        auth_code = auth_code_response.get('auth_code')
        if not auth_code:
            return {
                "success": False,
                "error": "No auth_code in response"
            }

        print(f"✅ Auth code generated successfully")

        # Step 3: Exchange auth code for access token
        session.set_token(auth_code)
        token_response = session.generate_token()

        print(f"📝 Token response: {json.dumps(token_response, indent=2)}")

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

        # Extract just the token part (after the colon)
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