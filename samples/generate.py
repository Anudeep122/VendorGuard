"""Regenerate samples/*.json (valid checksums, dates relative to today). Run: python samples/generate.py"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app.seed import write_sample_files, SAMPLES_DIR
write_sample_files()
print("wrote samples to", SAMPLES_DIR)
