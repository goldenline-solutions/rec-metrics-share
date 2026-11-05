from db import Base, engine
import models  # important: ensures model classes are imported/registered

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("✅ Postgres schema created from SQLAlchemy models.")
