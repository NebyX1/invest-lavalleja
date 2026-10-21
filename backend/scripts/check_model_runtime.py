"""Check the configured local model artifacts without contacting Hugging Face."""
import argparse
import os
from pathlib import Path
from .prepare_models import verify_runtime


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path,default=Path(os.environ.get('DATA_DIR','/app/data'))/'models')
    args=parser.parse_args()
    verify_runtime(args.model_dir)
