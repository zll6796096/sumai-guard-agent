#!/usr/bin/env python3
import sys
import os
import requests
import io
from PIL import Image

def main():
    base_url = os.getenv("SUMAI_AGENT_URL", "http://localhost:8000").rstrip("/")
    print(f"Running smoke test against agent backend at: {base_url}")
    
    # Check health/status
    try:
        status_res = requests.get(f"{base_url}/status", timeout=5)
        status_res.raise_for_status()
        status_data = status_res.json()
        print(f"Status check passed: {status_data}")
        if status_data.get("require_real_gemini") is not True:
            print("⚠️ Warning: Backend is not running with require_real_gemini=true. Make sure REQUIRE_REAL_GEMINI=true is set.")
    except Exception as e:
        print(f"❌ Failed to reach status endpoint: {e}")
        sys.exit(1)

    # 1. Test Home Image
    home_img_path = "apps/sumai_web/assets/samples/hallway_sample.png"
    if not os.path.exists(home_img_path):
        home_img_path = "../apps/sumai_web/assets/samples/hallway_sample.png"
    
    if not os.path.exists(home_img_path):
        print(f"❌ Could not find hallway_sample.png")
        sys.exit(1)

    print(f"Sending home interior image: {home_img_path}...")
    with open(home_img_path, "rb") as f:
        files = {"image": ("hallway.png", f.read(), "image/png")}
        data = {"room_hint": "hallway"}
        try:
            res = requests.post(f"{base_url}/analyze", files=files, data=data, timeout=60)
            if res.status_code != 200:
                print(f"❌ Home analysis failed with code {res.status_code}: {res.text}")
                sys.exit(1)
            
            payload = res.json()
            print("✅ Home analysis response received successfully!")
            print(f"   is_home_environment: {payload.get('is_home_environment')}")
            print(f"   findings count: {len(payload.get('findings', []))}")
            print(f"   overall_risk_level: {payload.get('overall_risk_level')}")
            
            # Assertions
            if payload.get("is_home_environment") is not True:
                print("❌ Assertion failed: is_home_environment should be True for home image.")
                sys.exit(1)
            
        except Exception as e:
            print(f"❌ Home analysis request failed: {e}")
            sys.exit(1)

    # 2. Test Non-Home Image (Solid color)
    print("Generating solid color non-home image...")
    non_home_img = Image.new("RGB", (300, 300), color="blue")
    buf = io.BytesIO()
    non_home_img.save(buf, format="PNG")
    non_home_bytes = buf.getvalue()

    print("Sending non-home image...")
    files = {"image": ("non_home.png", non_home_bytes, "image/png")}
    data = {"room_hint": "auto"}
    try:
        res = requests.post(f"{base_url}/analyze", files=files, data=data, timeout=60)
        if res.status_code != 200:
            print(f"❌ Non-home analysis failed with code {res.status_code}: {res.text}")
            sys.exit(1)
        
        payload = res.json()
        print("✅ Non-home analysis response received successfully!")
        print(f"   is_home_environment: {payload.get('is_home_environment')}")
        print(f"   not_applicable_reason_ja: {payload.get('not_applicable_reason_ja')}")
        print(f"   findings count: {len(payload.get('findings', []))}")
        print(f"   overall_risk_level: {payload.get('overall_risk_level')}")
        
        # Assertions
        if payload.get("is_home_environment") is not False:
            print("❌ Assertion failed: is_home_environment should be False for non-home image.")
            sys.exit(1)
        if len(payload.get("findings", [])) != 0:
            print("❌ Assertion failed: findings count should be 0 for non-home image.")
            sys.exit(1)
        if payload.get("overall_risk_level") != "low":
            print("❌ Assertion failed: overall_risk_level should be low for non-home image.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Non-home analysis request failed: {e}")
        sys.exit(1)

    print("\n🎉 ALL SMOKE TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
