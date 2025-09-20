# This is an example for a WEB SERVICE, not your bot.
# You would need to install Flask: pip install Flask

from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return "My web service is running!"

# This is the health check endpoint
@app.route("/healthz")
def health_check():
    # This endpoint simply returns a success message and a 200 OK status code.
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    # A web service listens on a port (e.g., 8000)
    app.run(host="0.0.0.0", port=8080)
