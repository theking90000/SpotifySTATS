# Use the official Python image from the Docker Hub
FROM python:3.10-alpine

# Set the working directory in the container
WORKDIR /app

COPY databases/ databases/

RUN pip install --no-cache-dir gunicorn markdown

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY import.py .

COPY web/ web/

COPY changelog.md .

RUN python -m markdown changelog.md > web/_changelog.html

COPY spot_server.py .

# Expose port 5000 for the Flask app
EXPOSE 5000

# Define environment variable
ENV FLASK_APP=spot_server.py
ENV SPOT_NO_API=1

# Run the Gunicorn server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "spot_server:app"]