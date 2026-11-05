"""
Batch ingestion script for processing multiple screenshot files.
Processes all image files in a specified folder and ingests them via the API.
"""
import os
import sys
import requests
from pathlib import Path
from typing import List, Dict, Any

# Supported image extensions
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}


def find_image_files(folder_path: str) -> List[str]:
    """
    Find all image files in the specified folder.
    
    Args:
        folder_path: Path to the folder containing images
        
    Returns:
        List of full paths to image files
    """
    folder = Path(folder_path)
    if not folder.exists():
        raise ValueError(f"Folder does not exist: {folder_path}")
    
    if not folder.is_dir():
        raise ValueError(f"Path is not a directory: {folder_path}")
    
    image_files = []
    for file_path in folder.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(str(file_path.absolute()))
    
    return sorted(image_files)


def ingest_image(
    api_url: str,
    image_path: str,
    season_label: str = None,
    mode_label: str = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Ingest a single image file via the API.
    
    Args:
        api_url: Base URL of the API (e.g., 'http://localhost:5000')
        image_path: Path to the image file
        season_label: Optional season label
        mode_label: Optional mode label
        verbose: Whether to print progress messages
        
    Returns:
        Response dictionary from the API
    """
    endpoint = f"{api_url}/api/ingest"
    
    try:
        with open(image_path, 'rb') as f:
            files = {'screenshot': (os.path.basename(image_path), f, 'image/png')}
            data = {}
            
            if season_label:
                data['season_label'] = season_label
            if mode_label:
                data['mode_label'] = mode_label
            
            response = requests.post(endpoint, files=files, data=data, timeout=120)
            response.raise_for_status()
            
            result = response.json()
            return result
            
    except requests.exceptions.RequestException as e:
        error_msg = f"API request failed: {str(e)}"
        if hasattr(e.response, 'text'):
            error_msg += f" - Response: {e.response.text}"
        raise Exception(error_msg)
    except Exception as e:
        raise Exception(f"Error processing {image_path}: {str(e)}")


def batch_ingest(
    folder_path: str,
    api_url: str = "http://localhost:5000",
    season_label: str = None,
    mode_label: str = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Process all image files in a folder.
    
    Args:
        folder_path: Path to folder containing images
        api_url: Base URL of the API
        season_label: Optional season label to apply to all games
        mode_label: Optional mode label to apply to all games
        verbose: Whether to print progress messages
        
    Returns:
        Summary dictionary with results
    """
    # Find all image files
    if verbose:
        print(f"Scanning folder: {folder_path}")
    
    image_files = find_image_files(folder_path)
    
    if not image_files:
        print(f"No image files found in {folder_path}")
        return {
            "total": 0,
            "processed": 0,
            "successful": 0,
            "duplicates": 0,
            "errors": 0,
            "results": []
        }
    
    if verbose:
        print(f"Found {len(image_files)} image file(s)")
        print("-" * 60)
    
    # Process each image
    results = {
        "total": len(image_files),
        "processed": 0,
        "successful": 0,
        "duplicates": 0,
        "errors": 0,
        "results": []
    }
    
    for idx, image_path in enumerate(image_files, 1):
        filename = os.path.basename(image_path)
        
        if verbose:
            print(f"[{idx}/{len(image_files)}] Processing: {filename}")
        
        try:
            result = ingest_image(
                api_url=api_url,
                image_path=image_path,
                season_label=season_label,
                mode_label=mode_label,
                verbose=False
            )
            
            results["processed"] += 1
            
            if result.get("stored", False):
                results["successful"] += 1
                game_id = result.get("game_id", "unknown")
                if verbose:
                    print(f"  ✓ Stored as new game: {game_id}")
            else:
                results["duplicates"] += 1
                game_id = result.get("game_id", "unknown")
                message = result.get("message", "Duplicate detected")
                if verbose:
                    print(f"  ⊘ Duplicate: {message} (game_id: {game_id})")
            
            results["results"].append({
                "file": filename,
                "status": "success",
                "game_id": game_id,
                "stored": result.get("stored", False),
                "message": result.get("message", "")
            })
            
        except Exception as e:
            results["errors"] += 1
            error_msg = str(e)
            if verbose:
                print(f"  ✗ Error: {error_msg}")
            
            results["results"].append({
                "file": filename,
                "status": "error",
                "error": error_msg
            })
        
        if verbose:
            print()
    
    # Print summary
    if verbose:
        print("=" * 60)
        print("BATCH INGESTION SUMMARY")
        print("=" * 60)
        print(f"Total files:     {results['total']}")
        print(f"Processed:       {results['processed']}")
        print(f"Successful:      {results['successful']} (new games stored)")
        print(f"Duplicates:      {results['duplicates']} (already existed)")
        print(f"Errors:          {results['errors']}")
        print("=" * 60)
    
    return results


def main():
    """Main entry point for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Batch ingest NBA2K Rec box score screenshots from a folder"
    )
    parser.add_argument(
        "folder",
        help="Path to folder containing image files"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:5000",
        help="Base URL of the API (default: http://localhost:5000)"
    )
    parser.add_argument(
        "--season-label",
        help="Season label to apply to all games"
    )
    parser.add_argument(
        "--mode-label",
        help="Mode label to apply to all games"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()
    
    try:
        results = batch_ingest(
            folder_path=args.folder,
            api_url=args.api_url,
            season_label=args.season_label,
            mode_label=args.mode_label,
            verbose=not args.quiet
        )
        
        # Exit with error code if there were errors
        if results["errors"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        print("\n\nBatch ingestion interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

