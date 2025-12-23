cmake_minimum_required(VERSION 3.10)
project(xmproxy-webapp VERSION 1.0.0)

# Install Python server and modules
install(PROGRAMS src/server.py
        DESTINATION bin
        RENAME xmproxy-webapp-server)

install(FILES
        src/config.py
        src/xmproxy_client.py
        src/config_manager.py
        DESTINATION bin)

# Install web assets
install(DIRECTORY share/www/
        DESTINATION share/www)

# Install default config
install(FILES etc/config.json.default
        DESTINATION etc)

# Generate and install manifest
configure_file(manifest.template.json
               ${CMAKE_CURRENT_BINARY_DIR}/manifest.json
               @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/manifest.json
        DESTINATION .)
