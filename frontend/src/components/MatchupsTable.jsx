import './MatchupsTable.css'

/**
 * MatchupsTable component - displays positional matchups between players
 * 
 * Props:
 * - matchups: array - array of matchup objects
 */
function MatchupsTable({ matchups }) {
  if (!matchups || matchups.length === 0) {
    return <p>No matchup data available</p>
  }

  return (
    <div className="matchups-table-container rtable-wrap">
      <table className="matchups-table rtable">
        <thead>
          <tr>
            <th>Defender</th>
            <th>Defender Position</th>
            <th>Offender</th>
            <th>Offender Position</th>
            <th>Matchup Type</th>
          </tr>
        </thead>
        <tbody>
          {matchups.map((matchup, idx) => (
            <tr key={idx}>
              <td data-label="Defender" className="gamertag-cell rtable-primary">{matchup.defender_gamertag}</td>
              <td data-label="Defender Position">{matchup.defender_position}</td>
              <td data-label="Offender" className="gamertag-cell">{matchup.offender_gamertag}</td>
              <td data-label="Offender Position">{matchup.offender_position}</td>
              <td data-label="Matchup Type">{matchup.matchup_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default MatchupsTable

