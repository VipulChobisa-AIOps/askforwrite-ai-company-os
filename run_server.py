import uvicorn
import sys
import multiprocessing
from dotenv import load_dotenv

if __name__ == '__main__':
    # PyInstaller multiprocessing support
    multiprocessing.freeze_support()
    
    # Load environment variables
    load_dotenv()
    
    print("Starting AskforWrite AI Company OS Server...")
    # Run the FastAPI app
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
