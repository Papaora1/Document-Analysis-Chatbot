import sys
from loguru import logger

# Configure Loguru to customize the log message format
logger.remove()  # Remove the default logger configuration
logger.add(
    sink=sys.stdout,  # Output to stdout (console)
    format="{time:YYYY-MM-DD HH:mm:ss} | {file} | {level} | {message}",  # Define custom log message format
)

# Configure Loguru to output log messages to the log file with rotation and retention
log_file_path = "../../logs/app.log"
logger.add(
    log_file_path,  # Output to log file
    rotation="10 MB",  # Rotate log file when it reaches 10 MB in size
    compression="zip",  # Compress old log files into zip archives
    retention="7 days",  # Retain log files for 7 days
    format="{time:YYYY-MM-DD HH:mm:ss} | {file} | {level} | {message}",  # Define custom log message format
)
