// v3.1.0
const CONFIG = {
  baseURI: '/',
  dbCleanInterval: 1000 * 60 * 60,
  dbPath: '/flood-db/',
  tempPath: '/tmp/',
  disableUsersAndAuth: true,
  configUser: {
    socket: true,
    socketPath: '/torrents/config/rtorrent/.rtorrent.sock'
  },
  floodServerHost: '127.0.0.1',
  floodServerPort: 3000,
  floodServerProxy: 'http://127.0.0.1:3000',
  maxHistoryStates: 30,
  torrentClientPollInterval: 1000 * 2,
  secret: 'j5if27cUE6X0oPNoc1gv8CRywPORFVWq',
  ssl: false,
  sslKey: '/absolute/path/to/key/',
  sslCert: '/absolute/path/to/certificate/',
  diskUsageService: {
    // assign desired mounts to include. Refer to "Mounted on" column of `df -P`
    watchMountPoints: [
      "/torrents"
    ]
  },
  // Allowed paths for file operations
  allowedPaths: ['/torrents'],
};
module.exports = CONFIG;