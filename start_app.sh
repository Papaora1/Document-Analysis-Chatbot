#!/bin/bash

# Start the Python backend
python3 app.py &

sleep 20
cd client

# Start the React frontend
npm start &
