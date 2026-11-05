"""
OpenAI client for extracting box score data from screenshots using Chat Completions API.
Uses Structured Outputs (json_schema strict mode) to guarantee schema compliance.
"""
import os
import base64
import json
import logging
from typing import Dict, Any, Optional, Tuple, List
from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # Default to vision-capable model

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

# Initialize client
# Note: If you get "unexpected keyword argument 'proxies'" error, it's likely due to:
# 1. Environment variables (HTTP_PROXY/HTTPS_PROXY) being automatically picked up
# 2. Version mismatch between openai and httpx libraries
# Solution: Update dependencies with: pip install --upgrade openai httpx
client = OpenAI(api_key=OPENAI_API_KEY)


# JSON Schema for validation structured output
VALIDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_valid_rec_screenshot": {
            "type": "boolean",
            "description": "True only if this is definitively a valid NBA2K Rec box score screenshot"
        },
        "has_basketball_stats": {
            "type": "boolean",
            "description": "True if the image contains basketball statistics (points, rebounds, assists, etc.)"
        },
        "has_player_gamertags": {
            "type": "boolean",
            "description": "True if the image contains player gamertags, usernames, or player identifiers (including AI players with generic names like 'AI Player' or 'CPU')"
        },
        "has_team_scores": {
            "type": "boolean",
            "description": "True if the image contains team scores (away/home or similar)"
        },
        "has_nba2k_interface": {
            "type": "boolean",
            "description": "True if the image shows NBA2K game interface elements"
        },
        "is_5v5_game": {
            "type": "boolean",
            "description": "True if the game is 5v5 (exactly 10 players total: 5 per team). Must be False for 3v3 (6 players) or 2v2 (4 players) games."
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation of why it is or isn't valid (only if invalid)"
        }
    },
    "required": ["is_valid_rec_screenshot", "has_basketball_stats", "has_player_gamertags", "has_team_scores", "has_nba2k_interface", "is_5v5_game", "reason"],
    "additionalProperties": False
}

# JSON Schema for structured output
BOX_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "season_label": {"type": ["string", "null"]},
                "mode_label": {"type": ["string", "null"]},
                "extracted_from": {"type": "string"},
                "platform_hint": {
                    "type": ["string", "null"],
                    "description": "Set to 'Console' if you see a small circular icon or platform logo (e.g. PlayStation, Xbox) immediately before player names on the scoreboard; otherwise 'PC' or null"
                },
                "has_platform_icons_before_names": {
                    "type": "boolean",
                    "description": "True if you see a small icon (e.g. circle, platform logo like PlayStation or Xbox) before each player name on the scoreboard"
                }
            },
            "required": ["season_label", "mode_label", "extracted_from", "platform_hint", "has_platform_icons_before_names"],
            "additionalProperties": False
        },
        "game": {
            "type": "object",
            "properties": {
                "away_score": {"type": "integer"},
                "home_score": {"type": "integer"},
                "quarters": {
                    "type": "object",
                    "properties": {
                        "away": {
                            "type": "array",
                            "items": {"type": ["integer", "null"]},
                            "minItems": 4,
                            "maxItems": 4
                        },
                        "home": {
                            "type": "array",
                            "items": {"type": ["integer", "null"]},
                            "minItems": 4,
                            "maxItems": 4
                        }
                    },
                    "required": ["away", "home"],
                    "additionalProperties": False
                }
            },
            "required": ["away_score", "home_score", "quarters"],
            "additionalProperties": False
        },
        "teams": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "side": {"type": "string", "enum": ["AWAY", "HOME"]},
                    "grade": {"type": ["string", "null"]},
                    "totals": {
                        "type": "object",
                        "properties": {
                            "pts": {"type": "integer"},
                            "reb": {"type": "integer"},
                            "ast": {"type": "integer"},
                            "stl": {"type": "integer"},
                            "blk": {"type": "integer"},
                            "fouls": {"type": "integer"},
                            "tov": {"type": "integer"},
                            "fgm": {"type": "integer"},
                            "fga": {"type": "integer"},
                            "tpm": {"type": "integer"},
                            "tpa": {"type": "integer"},
                            "ftm": {"type": "integer"},
                            "fta": {"type": "integer"}
                        },
                        "required": ["pts", "reb", "ast", "stl", "blk", "fouls", "tov", "fgm", "fga", "tpm", "tpa", "ftm", "fta"],
                        "additionalProperties": False
                    }
                },
                "required": ["side", "grade", "totals"],
                "additionalProperties": False
            },
            "minItems": 2,
            "maxItems": 2
        },
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "side": {"type": "string", "enum": ["AWAY", "HOME"]},
                    "row_index": {"type": "integer", "minimum": 0, "maximum": 4},
                    "gamertag": {"type": "string"},
                    "grade": {"type": ["string", "null"]},
                    "stats": {
                        "type": "object",
                        "properties": {
                            "pts": {"type": "integer"},
                            "reb": {"type": "integer"},
                            "ast": {"type": "integer"},
                            "stl": {"type": "integer"},
                            "blk": {"type": "integer"},
                            "fouls": {"type": "integer"},
                            "tov": {"type": "integer"},
                            "fgm": {"type": "integer"},
                            "fga": {"type": "integer"},
                            "tpm": {"type": "integer"},
                            "tpa": {"type": "integer"},
                            "ftm": {"type": "integer"},
                            "fta": {"type": "integer"}
                        },
                        "required": ["pts", "reb", "ast", "stl", "blk", "fouls", "tov", "fgm", "fga", "tpm", "tpa", "ftm", "fta"],
                        "additionalProperties": False
                    }
                },
                "required": ["side", "row_index", "gamertag", "grade", "stats"],
                "additionalProperties": False
            },
            "minItems": 10,
            "maxItems": 10
        },
        "indicated_matchups": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "defender_gamertag": {"type": "string"},
                    "offender_gamertag": {"type": "string"},
                    "defender_side": {"type": "string", "enum": ["AWAY", "HOME"]},
                    "offender_side": {"type": "string", "enum": ["AWAY", "HOME"]}
                },
                "required": ["defender_gamertag", "offender_gamertag", "defender_side", "offender_side"],
                "additionalProperties": False
            }
        }
    },
    "required": ["metadata", "game", "teams", "players", "indicated_matchups"],
    "additionalProperties": False
}


def encode_image_to_base64(image_path: str) -> str:
    """
    Encode an image file to base64 data URL format.
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Base64-encoded data URL string
    """
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        # Determine MIME type from file extension
        ext = os.path.splitext(image_path)[1].lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp"
        }
        mime_type = mime_types.get(ext, "image/png")
        return f"data:{mime_type};base64,{encoded_string}"


def validate_rec_screenshot(image_path: str) -> Tuple[bool, str]:
    """
    Validate that the uploaded image is actually a valid NBA2K Rec 5v5 box score screenshot.
    
    This function uses OpenAI Vision API with structured outputs to rigorously check if the image contains:
    - NBA2K Rec box score interface
    - Basketball statistics (points, rebounds, assists, etc.)
    - Player identifiers (gamertags, usernames, or AI player names)
    - Team scores
    - Game information
    - 5v5 game format (exactly 10 players: 5 per team, may include AI players)
    
    Args:
        image_path: Path to the screenshot image
        
    Returns:
        Tuple of (is_valid: bool, reason: str) where reason explains why it's invalid (empty if valid)
        
    Raises:
        ValueError: If validation fails due to API error
    """
    # Encode image to base64
    image_data_url = encode_image_to_base64(image_path)
    
    # Strict validation prompt - be very specific about what constitutes a valid screenshot
    validation_prompt = (
        "You are validating NBA2K Rec box score screenshots. Analyze this image carefully.\n\n"
        "A VALID NBA2K Rec box score screenshot MUST contain ALL of the following:\n"
        "1. Basketball statistics table with columns showing: PTS (points), REB (rebounds), AST (assists), STL (steals), BLK (blocks), etc.\n"
        "2. Player identifiers - EXACTLY 5 players per team, 10 players total (5v5 game format). Players may have:\n"
        "   - Human player gamertags/usernames\n"
        "   - AI player names (e.g., 'AI Player', 'CPU', generic names, or blank names)\n"
        "   - Any combination of human and AI players\n"
        "   Games with AI players are VALID as long as there are exactly 10 players total (5 per team)\n"
        "3. Team scores showing final scores for two teams (usually labeled AWAY and HOME or similar)\n"
        "4. NBA2K game interface elements (NBA2K branding, game UI, Rec mode indicators)\n"
        "5. Basketball game context (not a map, not a menu, not a different game)\n"
        "6. 5v5 game format - MUST have exactly 10 players total (5 per team). NOT 3v3 (6 players) or 2v2 (4 players)\n\n"
        "If the image is:\n"
        "- A map, landscape, or non-game image → INVALID\n"
        "- A menu screen, settings, or non-box-score screen → INVALID\n"
        "- A different game or sport → INVALID\n"
        "- Missing any of the required elements above → INVALID\n"
        "- Only partially showing stats or cut off → INVALID\n"
        "- A 3v3 game (6 players total, 3 per team) → INVALID (only 5v5 games are accepted)\n"
        "- A 2v2 game (4 players total, 2 per team) → INVALID (only 5v5 games are accepted)\n"
        "- Any game format other than 5v5 → INVALID\n\n"
        "IMPORTANT: Games with AI players (CPU players, bots, or players with generic/blank names) are VALID as long as:\n"
        "- There are exactly 10 players total (5 per team)\n"
        "- All other required elements are present\n"
        "- It's a 5v5 Rec game format\n\n"
        "Be strict. Only mark as valid if you can clearly see ALL required elements of a complete 5v5 Rec box score with exactly 10 players (human or AI)."
    )
    
    try:
        # Call OpenAI Chat Completions API with structured outputs for reliable validation
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        },
                        {
                            "type": "text",
                            "text": validation_prompt
                        }
                    ]
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ScreenshotValidation",
                    "strict": True,
                    "schema": VALIDATION_SCHEMA
                }
            },
            temperature=0.0  # Deterministic output
        )
        
        # Extract the JSON from response
        content = response.choices[0].message.content
        validation_result = json.loads(content)
        
        # Get the main validation flag
        is_valid = validation_result.get("is_valid_rec_screenshot", False)
        
        # Additional strict check: require ALL indicators to be true for validation to pass
        # This prevents false positives where the model might mark it valid but individual checks fail
        has_all_indicators = (
            validation_result.get("has_basketball_stats", False) and
            validation_result.get("has_player_gamertags", False) and
            validation_result.get("has_team_scores", False) and
            validation_result.get("has_nba2k_interface", False) and
            validation_result.get("is_5v5_game", False)  # Must be 5v5 game
        )
        
        # Only return True if BOTH the main flag is True AND all indicators are present (including 5v5)
        final_valid = is_valid and has_all_indicators
        
        # Build detailed reason if invalid
        reason = ""
        if not final_valid:
            base_reason = validation_result.get("reason", "Image does not appear to be a valid Rec box score screenshot")
            
            # Build detailed reason based on missing indicators
            missing_indicators = []
            if not validation_result.get("has_basketball_stats", False):
                missing_indicators.append("basketball statistics")
            if not validation_result.get("has_player_gamertags", False):
                missing_indicators.append("player identifiers (gamertags, usernames, or AI player names)")
            if not validation_result.get("has_team_scores", False):
                missing_indicators.append("team scores")
            if not validation_result.get("has_nba2k_interface", False):
                missing_indicators.append("NBA2K game interface")
            if not validation_result.get("is_5v5_game", False):
                # Check if it's a different game format
                if "3v3" in base_reason.lower() or "2v2" in base_reason.lower():
                    missing_indicators.append("5v5 game format (only 5v5 Rec games are accepted, not 3v3 or 2v2)")
                else:
                    missing_indicators.append("5v5 game format (must have exactly 10 players: 5 per team)")
            
            if missing_indicators:
                reason = f"{base_reason}. Missing required elements: {', '.join(missing_indicators)}."
            else:
                reason = base_reason
            
            logger.info("Screenshot validation failed: %s", reason)
            logger.info("Validation details: stats=%s, gamertags=%s, scores=%s, nba2k_ui=%s, is_5v5=%s",
                        validation_result.get('has_basketball_stats'), validation_result.get('has_player_gamertags'),
                        validation_result.get('has_team_scores'), validation_result.get('has_nba2k_interface'),
                        validation_result.get('is_5v5_game'))
        
        return (final_valid, reason)
        
    except Exception as e:
        # If validation API call fails, be conservative and reject the image
        # This prevents hallucinated data from invalid images
        logger.warning("Screenshot validation API call failed: %s", e)
        # Return False to block the image - better to reject than allow invalid data
        raise ValueError(
            f"Unable to validate screenshot. Please ensure you're uploading a valid NBA2K Rec box score screenshot. "
            f"Validation error: {str(e)}"
        )


def extract_box_score(image_path: str, retry_on_error: bool = True, validation_feedback: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Extract box score data from a screenshot using OpenAI Responses API with Structured Outputs.
    
    Args:
        image_path: Path to the screenshot image
        retry_on_error: Whether to retry once if the first attempt fails
        validation_feedback: Optional list of validation errors/warnings to include in prompt for retry
        
    Returns:
        Extracted JSON payload conforming to BoxScoreExtraction schema
        
    Raises:
        ValueError: If the image is not a valid rec screenshot
        Exception: If extraction fails after retries
    """
    # First, validate that this is a valid rec screenshot
    is_valid, reason = validate_rec_screenshot(image_path)
    if not is_valid:
        error_message = (
            "The uploaded image is not a valid NBA2K Rec box score screenshot. "
            f"{reason} "
            "Please upload a screenshot from the Rec box score screen showing player statistics, "
            "team scores, and game information."
        )
        raise ValueError(error_message)
    
    # Encode image to base64
    image_data_url = encode_image_to_base64(image_path)
    
    # Base instruction prompt
    base_instruction = (
        "Extract the stats exactly as shown. "
        "Preserve gamertags/player names exactly as displayed (including AI player names like 'AI Player', 'CPU', or generic names). "
        "Include any small icon or symbol that appears immediately before a name (e.g. a circle, or platform logo like PlayStation/Xbox)—do NOT strip these leading symbols; copy the gamertag exactly as shown so the first character may be that icon. "
        "Use integers. If a value is blank, use 0. "
        "If the screenshot shows specific defensive matchups (which player is guarding which player), "
        "extract them in the indicated_matchups array. If no matchups are clearly indicated, "
        "set indicated_matchups to null. "
        "Platform detection: Look specifically for a small circular icon or platform logo (e.g. PlayStation, Xbox, or a circle/dot) in front of each player name on the scoreboard. "
        "If you see such an icon before the names, set metadata.platform_hint to \"Console\" and metadata.has_platform_icons_before_names to true. "
        "If names start with normal text only (no icon), set metadata.platform_hint to \"PC\" or null and metadata.has_platform_icons_before_names to false. "
        "Return only JSON per schema."
    )
    
    # If validation feedback is provided, enhance the instruction
    if validation_feedback:
        feedback_text = "\n".join([f"- {error}" for error in validation_feedback])
        instruction = (
            f"{base_instruction}\n\n"
            "IMPORTANT: The previous extraction had validation errors. Please carefully review and fix:\n"
            f"{feedback_text}\n\n"
            "Ensure you extract exactly 10 players (5 per team: AWAY and HOME), each with a unique row_index (0-4) on their team. "
            "Make sure all required fields are present and correctly formatted."
        )
    else:
        instruction = base_instruction
    
    # Set metadata extracted_from
    metadata_extracted_from = "nba2k_rec_boxscore_screenshot"
    
    try:
        # Call OpenAI Chat Completions API with Structured Outputs
        # For vision models, use the standard content array format
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            },
                            # "detail": "high"
                        },
                        {
                            "type": "text",
                            "text": instruction
                        }
                    ]
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "BoxScoreExtraction",
                    "strict": True,
                    "schema": BOX_SCORE_SCHEMA
                }
            },
            temperature=0.0  # Deterministic output
        )
        
        # Extract the JSON from response
        content = response.choices[0].message.content
        extracted_data = json.loads(content)
        
        # Ensure metadata.extracted_from is set
        if "metadata" not in extracted_data:
            extracted_data["metadata"] = {}
        extracted_data["metadata"]["extracted_from"] = metadata_extracted_from
        
        return extracted_data
        
    except Exception as e:
        # Log OpenAI API error details (e.g. 400 body) for debugging
        err_body = getattr(e, "body", None)
        if err_body is not None:
            logger.warning("OpenAI extraction error body: %s", err_body)
        else:
            logger.warning("OpenAI extraction error: %s", e)
        if retry_on_error:
            # Retry once with a repair message
            try:
                error_msg = str(e)
                repair_instruction = (
                    f"{instruction}\n\n"
                    f"Previous attempt failed with error: {error_msg}. "
                    "Please ensure the output strictly conforms to the schema."
                )
                
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": image_data_url
                                    },
                                    # "detail": "high"
                                },
                                {
                                    "type": "text",
                                    "text": repair_instruction
                                }
                            ]
                        }
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "BoxScoreExtraction",
                            "strict": True,
                            "schema": BOX_SCORE_SCHEMA
                        }
                    },
                    temperature=0.0
                )
                
                content = response.choices[0].message.content
                extracted_data = json.loads(content)
                if "metadata" not in extracted_data:
                    extracted_data["metadata"] = {}
                extracted_data["metadata"]["extracted_from"] = metadata_extracted_from
                
                return extracted_data
                
            except Exception as retry_error:
                raise Exception(f"OpenAI extraction failed after retry: {retry_error}")
        else:
            raise


# JSON Schema for build sheet validation
BUILD_SHEET_VALIDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_valid_build_sheet": {
            "type": "boolean",
            "description": "True only if this is definitively a valid NBA 2K build attribute screen (Attribute Upgrades - Simple View)"
        },
        "has_attribute_list": {
            "type": "boolean",
            "description": "True if the image contains a list of player attributes (e.g., Close Shot, Driving Dunk, Three-Point Shot, etc.)"
        },
        "has_attribute_values": {
            "type": "boolean",
            "description": "True if the image shows numeric attribute values (current and max values)"
        },
        "has_position_info": {
            "type": "boolean",
            "description": "True if the image shows player position (PG, SG, SF, PF, C) or archetype information"
        },
        "has_nba2k_interface": {
            "type": "boolean",
            "description": "True if the image shows NBA 2K game interface elements or branding"
        },
        "is_simple_view": {
            "type": "boolean",
            "description": "True if the image shows the 'Simple View' format with attributes displayed in a grid/list format"
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation of why it is or isn't valid (only if invalid)"
        }
    },
    "required": ["is_valid_build_sheet", "has_attribute_list", "has_attribute_values", "has_position_info", "has_nba2k_interface", "is_simple_view", "reason"],
    "additionalProperties": False
}

# JSON Schema for build sheet extraction
BUILD_SHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "display_name": {
            "type": ["string", "null"],
            "description": "Build name/profile name as shown on the sheet. If not explicitly present, use fallback format."
        },
        "username": {
            "type": ["string", "null"],
            "description": "Player username/gamertag displayed in the top right corner of the screen. Extract exactly as shown (case-sensitive). If not visible, set to null."
        },
        "position": {
            "type": ["string", "null"],
            "description": "Player position (e.g., PG, SG, SF, PF, C)"
        },
        "archetype": {
            "type": ["string", "null"],
            "description": "Archetype line (e.g., '2-Way 3-Level Shot Creator')"
        },
        "physical": {
            "type": "object",
            "properties": {
                "height": {
                    "type": ["string", "null"],
                    "description": "Height as displayed (e.g., \"6'8\"\")"
                },
                "weight_lbs": {
                    "type": ["integer", "null"],
                    "description": "Weight in pounds (parsed if possible)"
                },
                "wingspan": {
                    "type": ["string", "null"],
                    "description": "Wingspan as displayed (e.g., \"6'9\"\")"
                }
            },
            "required": ["height", "weight_lbs", "wingspan"],
            "additionalProperties": False
        },
        "overall": {
            "type": "object",
            "properties": {
                "current": {
                    "type": ["integer", "null"],
                    "description": "Current overall rating"
                },
                "max": {
                    "type": ["integer", "null"],
                    "description": "Maximum overall rating if shown"
                }
            },
            "required": ["current", "max"],
            "additionalProperties": False
        },
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Attribute category (e.g., 'Finishing', 'Shooting', 'Playmaking', 'Defense', 'Physicals'). Use 'Attributes' as fallback if category not detectable."
                    },
                    "name": {
                        "type": "string",
                        "description": "Attribute name exactly as displayed (e.g., 'Driving Dunk', 'Close Shot')"
                    },
                    "current": {
                        "type": "integer",
                        "description": "Current value (bottom number)"
                    },
                    "max": {
                        "type": ["integer", "null"],
                        "description": "Maximum value (top 'Max' number if present)"
                    },
                    "order": {
                        "type": "integer",
                        "description": "Display order on screen (1-based index)"
                    }
                },
                "required": ["category", "name", "current", "max", "order"],
                "additionalProperties": False
            },
            "minItems": 10
        }
    },
    "required": ["display_name", "username", "position", "archetype", "physical", "overall", "attributes"],
    "additionalProperties": False
}

# Attribute name whitelist for validation
ATTRIBUTE_NAME_WHITELIST = {
    "Close Shot", "Driving Layup", "Driving Dunk", "Standing Dunk", "Post Control",
    "Mid-Range Shot", "Three-Point Shot", "Free Throw",
    "Pass Accuracy", "Ball Handle", "Speed With Ball",
    "Interior Defense", "Perimeter Defense", "Steal", "Block",
    "Offensive Rebound", "Defensive Rebound",
    "Speed", "Agility", "Strength", "Vertical"
}


def validate_build_sheet(image_path: str) -> Tuple[bool, str]:
    """
    Validate that the uploaded image is actually a valid NBA 2K build attribute screen.
    
    This function uses OpenAI Vision API with structured outputs to rigorously check if the image contains:
    - NBA 2K build attribute screen interface (Attribute Upgrades - Simple View)
    - List of player attributes (e.g., Close Shot, Driving Dunk, Three-Point Shot, etc.)
    - Numeric attribute values (current and max values)
    - Position or archetype information
    - NBA 2K game interface elements
    
    Args:
        image_path: Path to the screenshot image
        
    Returns:
        Tuple of (is_valid: bool, reason: str) where reason explains why it's invalid (empty if valid)
        
    Raises:
        ValueError: If validation fails due to API error
    """
    # Encode image to base64
    image_data_url = encode_image_to_base64(image_path)
    
    # Strict validation prompt - be very specific about what constitutes a valid build sheet
    validation_prompt = (
        "You are validating NBA 2K build attribute screenshots. Analyze this image carefully.\n\n"
        "A VALID NBA 2K build attribute screen (Attribute Upgrades - Simple View) MUST contain ALL of the following:\n"
        "1. A list/grid of player attributes showing attribute names such as:\n"
        "   - Close Shot, Driving Layup, Driving Dunk, Standing Dunk, Post Control (Finishing)\n"
        "   - Mid-Range Shot, Three-Point Shot, Free Throw (Shooting)\n"
        "   - Pass Accuracy, Ball Handle, Speed With Ball (Playmaking)\n"
        "   - Interior Defense, Perimeter Defense, Steal, Block (Defense)\n"
        "   - Offensive Rebound, Defensive Rebound, Speed, Agility, Strength, Vertical (Physicals)\n"
        "2. Numeric values for each attribute showing:\n"
        "   - Current value (bottom number)\n"
        "   - Maximum value (top 'Max' number if present)\n"
        "3. Player information such as:\n"
        "   - Position (PG, SG, SF, PF, C) or archetype (e.g., '2-Way 3-Level Shot Creator')\n"
        "   - Physical attributes (Height, Weight, Wingspan)\n"
        "   - Overall rating\n"
        "4. NBA 2K game interface elements:\n"
        "   - NBA 2K branding or UI elements\n"
        "   - 'Attribute Upgrades' or 'Simple View' text/labels\n"
        "   - Game menu interface typical of NBA 2K build screens\n"
        "5. Simple View format:\n"
        "   - Attributes displayed in a clear grid/list format\n"
        "   - Not a complex view or different screen type\n\n"
        "If the image is:\n"
        "- A box score, game screenshot, or different game screen → INVALID\n"
        "- A menu screen, settings, or non-build screen → INVALID\n"
        "- A different game or sport → INVALID\n"
        "- Missing any of the required elements above → INVALID\n"
        "- Only partially showing attributes or cut off → INVALID\n"
        "- A character creation screen or other non-attribute screen → INVALID\n"
        "- Any screen that is not the 'Attribute Upgrades - Simple View' → INVALID\n\n"
        "Be strict. Only mark as valid if you can clearly see ALL required elements of a complete NBA 2K build attribute screen."
    )
    
    try:
        # Call OpenAI Chat Completions API with structured outputs for reliable validation
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        },
                        {
                            "type": "text",
                            "text": validation_prompt
                        }
                    ]
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "BuildSheetValidation",
                    "strict": True,
                    "schema": BUILD_SHEET_VALIDATION_SCHEMA
                }
            },
            temperature=0.0  # Deterministic output
        )
        
        # Extract the JSON from response
        content = response.choices[0].message.content
        validation_result = json.loads(content)
        
        # Get the main validation flag
        is_valid = validation_result.get("is_valid_build_sheet", False)
        
        # Additional strict check: require ALL indicators to be true for validation to pass
        # This prevents false positives where the model might mark it valid but individual checks fail
        has_all_indicators = (
            validation_result.get("has_attribute_list", False) and
            validation_result.get("has_attribute_values", False) and
            validation_result.get("has_position_info", False) and
            validation_result.get("has_nba2k_interface", False) and
            validation_result.get("is_simple_view", False)
        )
        
        # Only return True if BOTH the main flag is True AND all indicators are present
        final_valid = is_valid and has_all_indicators
        
        # Build detailed reason if invalid
        reason = ""
        if not final_valid:
            base_reason = validation_result.get("reason", "Image does not appear to be a valid NBA 2K build attribute screen")
            
            # Build detailed reason based on missing indicators
            missing_indicators = []
            if not validation_result.get("has_attribute_list", False):
                missing_indicators.append("attribute list (e.g., Close Shot, Driving Dunk, Three-Point Shot)")
            if not validation_result.get("has_attribute_values", False):
                missing_indicators.append("attribute values (current and max numbers)")
            if not validation_result.get("has_position_info", False):
                missing_indicators.append("position or archetype information")
            if not validation_result.get("has_nba2k_interface", False):
                missing_indicators.append("NBA 2K game interface")
            if not validation_result.get("is_simple_view", False):
                missing_indicators.append("Simple View format")
            
            if missing_indicators:
                reason = f"{base_reason}. Missing required elements: {', '.join(missing_indicators)}."
            else:
                reason = base_reason
            
            logger.info("Build sheet validation failed: %s", reason)
            logger.info("Validation details: attribute_list=%s, attribute_values=%s, position_info=%s, nba2k_ui=%s, is_simple_view=%s",
                        validation_result.get('has_attribute_list'), validation_result.get('has_attribute_values'),
                        validation_result.get('has_position_info'), validation_result.get('has_nba2k_interface'),
                        validation_result.get('is_simple_view'))
        
        return (final_valid, reason)
        
    except Exception as e:
        # If validation API call fails, be conservative and reject the image
        # This prevents hallucinated data from invalid images
        logger.warning("Build sheet validation API call failed: %s", e)
        # Return False to block the image - better to reject than allow invalid data
        raise ValueError(
            f"Unable to validate build sheet. Please ensure you're uploading a valid NBA 2K build attribute screen "
            f"(Attribute Upgrades - Simple View). Validation error: {str(e)}"
        )


def extract_build_sheet_simple_view(image_path: str) -> Dict[str, Any]:
    """
    Extract build data from NBA 2K "Attribute Upgrades - Simple View" screenshot.
    
    Args:
        image_path: Path to the screenshot image
        
    Returns:
        Extracted JSON payload conforming to BuildSheetExtraction schema
        
    Raises:
        ValueError: If extraction fails or validation fails
    """
    # First, validate that this is a valid build attribute screen
    is_valid, reason = validate_build_sheet(image_path)
    if not is_valid:
        error_message = (
            "The uploaded image is not a valid NBA 2K build attribute screen. "
            f"{reason} "
            "Please upload a screenshot from the 'Attribute Upgrades - Simple View' screen showing "
            "player attributes, position, archetype, and attribute values."
        )
        raise ValueError(error_message)
    
    # Encode image to base64
    image_data_url = encode_image_to_base64(image_path)
    
    # Instruction prompt
    instruction = (
        "Extract build data from this NBA 2K 'Attribute Upgrades - Simple View' screenshot.\n\n"
        "Extract the following:\n"
        "1. Build name/profile name (if visible on sheet)\n"
        "2. Username/gamertag from the top right corner of the screen (extract exactly as shown, case-sensitive)\n"
        "3. Position (PG/SG/SF/PF/C) from top-right header\n"
        "4. Archetype string (e.g., '2-Way 3-Level Shot Creator')\n"
        "5. Physical attributes: Height (HT), Weight (WT), Wingspan (WS) from top-right header\n"
        "6. Overall rating: current and max (if shown, e.g., '94' and '99 MAX')\n"
        "7. All attributes with:\n"
        "   - Attribute name (exactly as displayed, vertical text)\n"
        "   - Top 'Max' number (if present)\n"
        "   - Bottom current value\n"
        "   - Category (Finishing, Shooting, Playmaking, Defense, Physicals) - use 'Attributes' if not detectable\n"
        "   - Display order (1-based index)\n\n"
        "Rules:\n"
        "- Use 'current' for the bottom number\n"
        "- Use 'max' for the top number if present\n"
        "- Keep attribute names exactly as displayed\n"
        "- Extract username/gamertag from the top right corner exactly as shown (preserve case, spaces, special characters)\n"
        "- If username is not visible or cannot be determined, set it to null\n"
        "- If uncertain about any field, set it to null rather than guessing\n"
        "- If build name is not explicitly present, use format: '{position or UNK} - {archetype or Build} - {timestamp}'\n"
        "- Do not invent categories if you cannot see them (use 'Attributes' fallback)\n"
        "- Return ONLY valid JSON matching the schema\n"
    )
    
    try:
        # Call OpenAI Chat Completions API with Structured Outputs
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        },
                        {
                            "type": "text",
                            "text": instruction
                        }
                    ]
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "BuildSheetExtraction",
                    "strict": True,
                    "schema": BUILD_SHEET_SCHEMA
                }
            },
            temperature=0.0  # Deterministic output
        )
        
        # Extract the JSON from response
        content = response.choices[0].message.content
        extracted_data = json.loads(content)
        
        # Server-side validation
        attributes = extracted_data.get("attributes", [])
        if len(attributes) < 10:
            raise ValueError(f"Extraction validation failed: Found only {len(attributes)} attributes, expected at least 10")
        
        # Validate that every attribute has name + current int
        for attr in attributes:
            if not attr.get("name") or not isinstance(attr.get("current"), int):
                raise ValueError("Extraction validation failed: Every attribute must have name and current integer value")
        
        # Validate attribute names against whitelist (at least 12 recognized names)
        recognized_names = set()
        for attr in attributes:
            attr_name = attr.get("name", "").strip()
            # Check if attribute name matches any in whitelist (case-insensitive, partial match)
            for whitelist_name in ATTRIBUTE_NAME_WHITELIST:
                if whitelist_name.lower() in attr_name.lower() or attr_name.lower() in whitelist_name.lower():
                    recognized_names.add(whitelist_name)
                    break
        
        if len(recognized_names) < 12:
            raise ValueError(
                f"Extraction validation failed: Only {len(recognized_names)} recognized attribute names found "
                f"(expected at least 12). Found: {recognized_names}"
            )
        
        # Coerce numeric strings to ints and strip whitespace
        if extracted_data.get("physical", {}).get("weight_lbs"):
            try:
                weight = extracted_data["physical"]["weight_lbs"]
                if isinstance(weight, str):
                    # Try to extract number from string
                    import re
                    numbers = re.findall(r'\d+', weight)
                    if numbers:
                        extracted_data["physical"]["weight_lbs"] = int(numbers[0])
                    else:
                        extracted_data["physical"]["weight_lbs"] = None
                elif not isinstance(weight, int):
                    extracted_data["physical"]["weight_lbs"] = None
            except (ValueError, TypeError):
                extracted_data["physical"]["weight_lbs"] = None
        
        # Strip whitespace from string fields
        if extracted_data.get("display_name"):
            extracted_data["display_name"] = extracted_data["display_name"].strip()
        if extracted_data.get("username"):
            extracted_data["username"] = extracted_data["username"].strip()
        if extracted_data.get("position"):
            extracted_data["position"] = extracted_data["position"].strip()
        if extracted_data.get("archetype"):
            extracted_data["archetype"] = extracted_data["archetype"].strip()
        
        # Note: We keep current > max if it happens (cap breakers), don't clamp
        
        return extracted_data
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse extraction response as JSON: {str(e)}")
    except Exception as e:
        if "validation failed" in str(e).lower():
            raise ValueError(str(e))
        raise Exception(f"OpenAI build extraction failed: {str(e)}")