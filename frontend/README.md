# NBA2K Rec Box Score Frontend

React web application for uploading NBA2K Rec box score screenshots and viewing ingested game data.

## Tech Stack

- **React 18** - UI library
- **Vite** - Build tool and dev server
- **React Router** - Client-side routing
- **Fetch API** - HTTP requests (no axios required)
- **CSS** - Component styling

## Setup

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure Backend URL

Create a `.env` file in the `frontend/` directory:

```bash
VITE_API_BASE_URL=http://localhost:5000
```

**Note:** The default backend URL is `http://localhost:5000` if no `.env` file is provided.

### 3. Start Development Server

```bash
npm run dev
```

The app will be available at `http://localhost:5173` (or the next available port).

## Building for Production

```bash
npm run build
```

The built files will be in the `dist/` directory.

## Project Structure

```
frontend/
├── src/
│   ├── components/          # Reusable React components
│   │   ├── UploadDropzone.jsx
│   │   ├── BoxScoreSummary.jsx
│   │   ├── PlayerTable.jsx
│   │   ├── MatchupsTable.jsx
│   │   └── JsonViewer.jsx
│   ├── pages/               # Page components
│   │   ├── UploadPage.jsx
│   │   ├── GamesListPage.jsx
│   │   └── GameDetailsPage.jsx
│   ├── utils/               # Utility functions
│   │   └── api.js           # API client functions
│   ├── App.jsx              # Main app component with routing
│   ├── main.jsx             # Entry point
│   └── index.css           # Global styles
├── index.html
├── package.json
├── vite.config.js
└── README.md
```

## Features

### Upload Page (`/`)
- Drag-and-drop file upload zone
- File picker button
- Image preview
- "Ingest Screenshot" button
- Loading states and progress messages
- Success/error messages
- Displays extracted JSON data
- Shows compact box score summary:
  - Final score
  - Quarter scores
  - Team totals
  - Player rows with stats
  - Positional matchups list
- Displays validation warnings from backend

### Games List Page (`/games`)
- Table of all ingested games
- Columns: Date, Score, Teams, Season, Mode, Details link
- Click "View Details" to see full game information
- Empty state when no games exist

### Game Details Page (`/games/:id`)
- Complete game information
- Box score summary
- Full player statistics table
- Positional matchups table
- Complete JSON payload viewer (expandable)

## API Integration

The frontend communicates with the Flask backend at the URL specified in `VITE_API_BASE_URL`. The following endpoints are used:

- `POST /api/ingest` - Upload and ingest a screenshot
- `GET /api/games` - Get list of all games
- `GET /api/games/:id` - Get detailed game information

All API functions are in `src/utils/api.js` and use the Fetch API.

## Environment Variables

- `VITE_API_BASE_URL` - Base URL for the Flask backend (default: `http://localhost:5000`)

**Important:** Vite requires the `VITE_` prefix for environment variables to be exposed to the client code.

## Development Notes

- The app uses React Router for client-side navigation
- All API calls are handled through utility functions in `src/utils/api.js`
- Error handling is implemented at the page level with user-friendly error messages
- Loading states are shown during API calls
- The UI is responsive and uses CSS for styling (no external CSS frameworks)

## Troubleshooting

**Backend connection errors:**
- Ensure the Flask backend is running on the port specified in `VITE_API_BASE_URL`
- Check CORS settings in the backend (should allow `http://localhost:5173`)
- Verify the backend API endpoints are working by testing with curl or Postman

**Build errors:**
- Make sure all dependencies are installed: `npm install`
- Check Node.js version (recommended: 18+)
- Clear node_modules and reinstall if needed: `rm -rf node_modules && npm install`

