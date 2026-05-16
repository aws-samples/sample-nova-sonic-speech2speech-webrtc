'use strict';

// Set source/public directories BEFORE anything else loads
process.env.REACT_APP_SRC_DIR = 'src_multi_party';
process.env.REACT_APP_PUBLIC_DIR = 'public_multi_party';
process.env.PORT = process.env.PORT || '3001';

// Now run the standard start script (paths.js will read our env vars)
require('./start');
