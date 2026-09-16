import os
from flask import Flask, render_template, request, jsonify
import boto3

app = Flask(__name__)

# --- AWS S3 CONFIGURATIONS ---
S3_BUCKET = (
    os.environ.get("AWS_S3_BUCKET") 
    or os.environ.get("S3_BUCKET") 
    or os.environ.get("AWS_S3_BUCKET_NAME")
    or "property-images-estatex-1"
)

AWS_ACCESS_KEY = (
    os.environ.get("AWS_ACCESS_KEY_ID") 
    or os.environ.get("AWS_ACCESS_KEY")
)

AWS_SECRET_KEY = (
    os.environ.get("AWS_SECRET_ACCESS_KEY") 
    or os.environ.get("AWS_SECRET_KEY")
)

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)


# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload-s3', methods=['POST'])
def upload_s3():
    if 'images' not in request.files:
        return jsonify({"success": False, "error": "No images provided"}), 400
    
    files = request.files.getlist('images')
    
    # सीरियल ऑर्डर बनाए रखने के लिए नाम के आधार पर सॉर्ट करना
    files.sort(key=lambda f: f.filename)
    
    uploaded_urls = []

    try:
        for file in files:
            filename = file.filename
            
            s3_client.upload_fileobj(
                file,
                S3_BUCKET,
                filename,
                ExtraArgs={'ContentType': file.content_type}
            )
            file_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{filename}"
            uploaded_urls.append(file_url)
        
        return jsonify({"success": True, "urls": uploaded_urls}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
    
