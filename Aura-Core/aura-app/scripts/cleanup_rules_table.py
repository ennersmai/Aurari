"""
Cleanup script: Drop the old 'rule' table and migrate to 'insight' system.

Run this after updating to the new Insight-based Learning Engine.
"""

import asyncio
import logging
from aura.db.client import get_db_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup_database():
    """Drop the rule table and prepare for insight system."""
    db = get_db_client()
    
    try:
        logger.info("🔌 Connecting to SurrealDB...")
        await db.connect()
        logger.info("✅ Connected to database")
        
        # Check if rule table exists
        logger.info("🔍 Checking for 'rule' table...")
        rule_count_result = await db.query("SELECT count() FROM rule GROUP ALL")
        
        if rule_count_result and len(rule_count_result) > 0:
            rule_count = rule_count_result[0].get("count", 0)
            logger.info(f"📊 Found {rule_count} existing rules in database")
            
            # Optional: Backup rules before dropping (can export to JSON)
            if rule_count > 0:
                logger.warning("⚠️  Rules will be deleted. Creating backup...")
                try:
                    rules = await db.query("SELECT * FROM rule")
                    import json
                    from datetime import datetime
                    
                    backup_file = f"rules_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    with open(backup_file, 'w') as f:
                        json.dump(rules, f, indent=2, default=str)
                    
                    logger.info(f"✅ Backup saved to: {backup_file}")
                except Exception as e:
                    logger.warning(f"⚠️  Could not create backup: {e}")
        else:
            logger.info("ℹ️  No rules found in database (table may not exist yet)")
        
        # Drop the rule table
        logger.info("🗑️  Dropping 'rule' table...")
        await db.query("REMOVE TABLE rule")
        logger.info("✅ Rule table removed successfully!")
        
        # Verify insight table structure (will be created automatically on first insert)
        logger.info("🔍 Verifying 'insight' table setup...")
        insight_count_result = await db.query("SELECT count() FROM insight GROUP ALL")
        
        if insight_count_result and len(insight_count_result) > 0:
            insight_count = insight_count_result[0].get("count", 0)
            logger.info(f"✅ Insight table exists with {insight_count} records")
        else:
            logger.info("ℹ️  Insight table will be created automatically on first use")
        
        logger.info("\n" + "="*60)
        logger.info("✨ DATABASE CLEANUP COMPLETE")
        logger.info("="*60)
        logger.info("✅ Old 'rule' table removed")
        logger.info("✅ Ready for Insight-based learning system")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        raise
    finally:
        await db.close()
        logger.info("🔌 Database connection closed")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧹 LEARNING ENGINE CLEANUP SCRIPT")
    print("="*60)
    print("This script will:")
    print("  1. Backup existing rules (if any)")
    print("  2. Drop the 'rule' table")
    print("  3. Prepare for Insight-based system")
    print("="*60)
    
    response = input("\n⚠️  Proceed with cleanup? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        print("\n🚀 Starting cleanup...\n")
        asyncio.run(cleanup_database())
    else:
        print("❌ Cleanup cancelled")

