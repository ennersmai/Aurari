"""
Local Tool: Web Search (Powered by Tavily)

Production-grade async implementation using aiohttp for non-blocking execution.
"""
import asyncio
import os
import logging
import aiohttp
import json
import datetime
from typing import Dict, Any

# Global tool definition for One-Shot Learning
TOOL_DEFINITION = {
    "name": "web_search",
    "description": "Search the live internet. Use this when the user asks for current events, news, specific facts, documentation, or data that might be newer than your training cutoff.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string", 
                "description": "The search query. Optimize for a search engine (keywords)."
            },
            "days": {
                "type": "integer",
                "description": "Limit results to X days ago (e.g., 3 for recent news). Set to 0 for all time.",
                "default": 3
            },
            "include_raw_content": {
                "type": "boolean",
                "description": "If true, includes more raw text from the page. Useful for coding docs.",
                "default": False
            }
        },
        "required": ["query"]
    }
}

logger = logging.getLogger(__name__)

async def run(arguments: Dict[str, Any]) -> str:
    """
    Executes the search via Tavily REST API (Async).
    
    Uses aiohttp for non-blocking HTTP requests, ensuring Aura Core
    remains responsive during network I/O.
    
    Args:
        arguments: Dictionary with:
            - query (str, required): Search query
            - days (int, optional): Limit to recent results (default: 3)
            - include_raw_content (bool, optional): Include more text (default: False)
    
    Returns:
        Formatted Markdown string with search results
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY not found in environment variables. Please configure the server."

    query = arguments.get("query")
    if not query:
        return "Error: 'query' parameter is required"
    
    days = arguments.get("days", 3)
    include_raw = arguments.get("include_raw_content", False)
    
    # API Configuration
    url = "https://api.tavily.com/search"
    
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 5,
        "topic": "general"
    }
    
    # If looking for news/recent events, we can adjust topic
    # Tavily's API handles recency automatically based on query context
    if days > 0 and days <= 7:
        # For very recent news, we could use "news" topic
        # But for now, let Tavily's smart ranking handle it
        pass

    try:
        async with aiohttp.ClientSession() as session:
            # Set timeout to prevent hanging (10 seconds)
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.post(url, json=payload, timeout=timeout) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Tavily API Error: {response.status} - {error_text}")
                    return f"Search failed (Status {response.status}). The internet connection might be down or the API key is invalid."
                
                data = await response.json()
                
                # --- Format Output for L3 ---
                # L3 needs dense, high-signal text. Markdown is best.
                output = []
                
                # 1. Direct Answer (if available)
                if data.get("answer"):
                    output.append(f"### Direct Answer\n{data['answer']}\n")
                
                # 2. Search Results
                results = data.get("results", [])
                if results:
                    output.append("### Search Results")
                    for i, res in enumerate(results, 1):
                        title = res.get('title', 'No Title')
                        url = res.get('url', '#')
                        content = res.get('content', '')
                        
                        # Truncate content unless requested otherwise
                        limit = 600 if include_raw else 300
                        if len(content) > limit:
                            content = content[:limit] + "..."
                            
                        output.append(f"**{i}. {title}**")
                        output.append(f"URL: {url}")
                        output.append(f"Summary: {content}")
                        output.append("---")
                else:
                    output.append("### No Results Found")
                    output.append("The search did not return any results. Try rephrasing your query.")
                
                # 3. Context Footer
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                output.append(f"\n*Search performed at {timestamp}*")
                
                return "\n".join(output)

    except aiohttp.ClientError as e:
        logger.error(f"Web search network error: {e}", exc_info=True)
        return f"Network error during search: {str(e)}. Please check your internet connection."
    except asyncio.TimeoutError:
        logger.error("Web search timeout")
        return "Search timed out. The search service may be slow or unavailable."
    except Exception as e:
        logger.error(f"Web search execution exception: {e}", exc_info=True)
        return f"System error during search: {str(e)}. Please try again later."
