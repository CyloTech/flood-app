const CONFIG = {
  baseURI: '/',
  dbCleanInterval: 1000 * 60 * 60,
  dbPath: '/flood-db/',
  floodServerPort: 80,
  maxHistoryStates: 30,
  pollInterval: 1000 * 5,
  secret: 'fgwi8r74389iurewhr',
  scgi: {
    host: 'localhost',
    port: 5000,
    socket: true,
    socketPath: '/torrents/config/rtorrent/.rtorrent.sock'
  }
};

module.exports = CONFIG;