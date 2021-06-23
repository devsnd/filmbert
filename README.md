# filmbert
Watch videos synchronized with your friends in the browser

## Installation

Install all requirements in a virtualenv

1. Create a venv

	virtualenv -p python3 venv

2. Activate the venv

	source venv/bin/activate

3. Install requirements

	pip install -r requirements.txt

## Usage

```
./app.py --video ./static/movie.mp4

options:
	--port <number>
	--host <host>
	--subtitle <path to subtitle>
```
