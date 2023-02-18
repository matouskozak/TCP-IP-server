import socket
import logging
import threading

logging.basicConfig(level = logging.DEBUG)
socket.setdefaulttimeout(10) # timeout


HOST_IP = "127.0.0.1"   # localhost
PORT = 3999

SERVER_KEY = 54621
CLIENT_KEY = 45328

# SERVER MESSAGES
# SERVER_CONFIRMATION = ""
SERVER_MOVE         = "102 MOVE"
SERVER_TURN_LEFT    = "103 TURN LEFT"
SERVER_TURN_RIGHT   = "104 TURN RIGHT"
SERVER_PICK_UP      = "105 GET MESSAGE"
SERVER_LOGOUT       = "106 LOGOUT"
SERVER_OK           = "200 OK"
SERVER_LOGIN_FAILED = "300 LOGIN FAILED"
SERVER_SYNTAX_ERROR = "301 SYNTAX ERROR"
SERVER_LOGIC_ERROR  = "302 LOGIC ERROR"

# CLIENT MESSAGES
# CLIENT_USERNAME     = ""
# CLIENT_CONFIRMATION = ""
CLIENT_OK           = "OK"
CLIENT_RECHARGING   = "RECHARGING"
CLIENT_FULL_POWER   = "FULL POWER"
# CLIENT_MESSAGE      = ""

# MAX CONSTANTS
CLIENT_USERNAME_MAX_LENGTH = 12
CLIENT_CONFIRMATION_MAX_LENGTH = 7
CLIENT_OK_MAX_LENGTH = 12
CLIENT_RECHARGING_MAX_LENGTH = 12
CLIENT_FULL_POWER_MAX_LENGTH = 12
CLIENT_MESSAGE_MAX_LENGTH = 100

TIMEOUT = 1
TIMEOUT_RECHARGING = 5

CONFIRMATION_NUMBER_MAX_DIGITS = 5
MAX_VALUE = 65536

# Directions
UP = -1
DOWN = -2
LEFT = 3
RIGHT = 4

DESTINATION_SQUARE = (-2, 2)


class ServerLoginFailed(Exception):
    pass


class ServerSyntaxError(Exception):
    pass


class ServerLogicError(Exception):
    pass


# Calculate hash from string
def calculate_hash(string):
    return (sum(map(lambda c: ord(c), string), 0) * 1000) % MAX_VALUE


class ClientConnection(threading.Thread):
    def __init__(self, connection, ip):
        super(ClientConnection, self).__init__()
        self.connection = connection
        self.ip = ip
        self.buffer = ''

    # Parse content of the buffer
    # raise ServerSyntaxError exception when missing "\a\b"
    def parse_buffer(self):
        msg_parts = self.buffer.partition("\a\b")
        logging.debug("Buffer contents: {}".format(msg_parts))
        next_message = msg_parts[0]

        if msg_parts[1]:    # Found "\a\b
            logging.debug("Next message from buffer: {}".format(next_message))
            self.buffer = msg_parts[2]

            return next_message

        raise ServerSyntaxError("Unrecognized message: {}".format(next_message))

    # Get next message from client
    # raise ServerSyntaxError exception when message too long
    # waits for next message if robot recharging
    def get_message(self, max_length):
        logging.debug("Buffer: '{}'".format(self.buffer))
        # Waiting for message
        while not ("\a\b" in self.buffer):
            remainder = max_length - len(self.buffer)
            if ("\a" in self.buffer and remainder <= 0) \
                    or (not ("\a" in self.buffer) and remainder <= 0):
                raise ServerSyntaxError("Message too long")

            raw_data = self.connection.recv(128)
            if len(raw_data) > 0:
                logging.debug("Received: {}".format(raw_data))
                decoded = raw_data.decode("ASCII")

                self.buffer += decoded

        # Parsing message
        msg = self.parse_buffer()

        if msg == CLIENT_RECHARGING:
            self.recharging()
            return self.get_message(max_length)

        msg_len = len(msg)
        # Message longer than expected
        if msg_len > max_length - 2:
            logging.error("Expected message with length {}, "
                          "got '{}' with len '{}'".format(max_length - 2, msg, msg_len))
            raise ServerSyntaxError("Message too long")

        return msg

    # Send message back to client
    def send_message(self, message):
        self.connection.send((message + "\a\b").encode("utf-8"))

    # Parse number from client
    # raise ServerSyntaxError if containing whitespace
    @staticmethod
    def parse_number(string_number):
        if " " in string_number:
            raise ServerSyntaxError("Number contains whitespace")
        return int(string_number)

    # Waits for recharge message from the client
    # raise ServerLogicError if doesn't receive CLIENT_FULL_POWER message
    def recharging(self):
        self.connection.settimeout(TIMEOUT_RECHARGING)
        logging.info("Robot recharging...")
        msg = self.get_message(CLIENT_FULL_POWER_MAX_LENGTH)

        if msg == CLIENT_FULL_POWER:
            self.connection.settimeout(TIMEOUT)
            return

        raise ServerLogicError("Expected message: {}, got '{}'".format(CLIENT_FULL_POWER, msg))

    # Authenticate client with hash exchange method
    # raise ServerLoginFailed exception if authentication fails
    def authenticate(self):
        logging.info("Authentication started...")
        username = self.get_message(CLIENT_USERNAME_MAX_LENGTH)
        logging.info("User {}".format(username))
        username_hash = calculate_hash(username)

        server_code = (username_hash + SERVER_KEY) % MAX_VALUE
        self.send_message(str(server_code))

        client_code = (username_hash + CLIENT_KEY) % MAX_VALUE
        client_confirmation = self.parse_number(self.get_message(CLIENT_CONFIRMATION_MAX_LENGTH))

        if client_code == client_confirmation:
            self.send_message(str(SERVER_OK))
            logging.info("Authentication completed...")
        else:
            raise ServerLoginFailed("Expected code: {}, but received {}".format(client_code, client_confirmation))

    # Parse CLIENT_OK command and return tuple with coordinates
    # raise ServerSyntaxError if message not correctly formatted
    @staticmethod
    def parse_client_ok(client_ok):
        try:
            ok, num_1, num_2 = client_ok.split(maxsplit = 2)
            if ok != CLIENT_OK:
                raise
            return ClientConnection.parse_number(num_1), ClientConnection.parse_number(num_2)
        except Exception:
            raise ServerSyntaxError("Expected {} <x> <y>, got {}".format(CLIENT_OK, client_ok))

    # Make robot move forward, waits until move is proceeded
    def move_forward(self, current_coords):
        new_coords = current_coords

        while current_coords == new_coords: # Waits for movement
            self.send_message(SERVER_MOVE)
            new_coords = self.parse_client_ok(self.get_message(CLIENT_OK_MAX_LENGTH))

        logging.info("Move from {} to {}".format(current_coords, new_coords))
        return new_coords

    # Make robot turn left
    def turn_left(self):
        self.send_message(SERVER_TURN_LEFT)
        return self.parse_client_ok(self.get_message(CLIENT_OK_MAX_LENGTH))

    # Make robot turn right
    def turn_right(self):
        self.send_message(SERVER_TURN_RIGHT)
        return self.parse_client_ok(self.get_message(CLIENT_OK_MAX_LENGTH))

    # Determines direction based on movement from coords_1 to coords_2
    # TODO not used
    @staticmethod
    def get_current_direction(coords_1, coords_2):
        x_diff = coords_2[0] - coords_1[0]
        y_diff = coords_2[1] - coords_1[1]

        if x_diff > 0:
            return RIGHT
        elif x_diff < 0:
            return LEFT
        elif y_diff > 0:
            return UP
        else:
            return DOWN

    # Determines direction from current to destination
    @staticmethod
    def get_direction_to_dest(current, destination):
        if destination[0] > current[0]:
            return RIGHT
        elif destination[0] < current[0]:
            return LEFT
        elif destination[1] > current[1]:
            return UP
        else:
            return DOWN

    # Turns robot to face destination_direction
    def turn_to_direction(self, direction, direction_to_dest):
        logging.debug("From {} to {}".format(direction, direction_to_dest))
        if direction != direction_to_dest:  # Correct direction
            if ((direction > 0 and direction_to_dest > 0)
                    or (direction < 0 and direction_to_dest < 0)):  # Opposite direction
                self.turn_left()
                self.turn_left()
            elif direction == UP:
                if direction_to_dest == LEFT:
                    self.turn_left()
                else:
                    self.turn_right()
            elif direction == DOWN:
                if direction_to_dest == LEFT:
                    self.turn_right()
                else:
                    self.turn_left()
            elif direction == RIGHT:
                if direction_to_dest == UP:
                    self.turn_left()
                else:
                    self.turn_right()
            elif direction == LEFT:
                if direction_to_dest == UP:
                    self.turn_right()
                else:
                    self.turn_left()
        return direction_to_dest

    # Reach destination square
    def find_and_search_square(self):
        logging.info("Reaching destination square")

        # Determine directions
        self.send_message(SERVER_TURN_LEFT)
        start_coords = self.parse_client_ok(self.get_message(CLIENT_OK_MAX_LENGTH))
        current_coords = self.move_forward(start_coords)
        direction = self.get_direction_to_dest(start_coords, current_coords)
        logging.debug("Initial direction {}".format(direction))

        # Reach destination square
        while current_coords != DESTINATION_SQUARE:
            direction_to_dest = self.get_direction_to_dest(current_coords, DESTINATION_SQUARE)
            direction = self.turn_to_direction(direction, direction_to_dest)
            current_coords = self.move_forward(current_coords)

        logging.info("Destination square reached")

        # Search square
        self.search_square(direction)

    # Sends command to pick up message and waits for response
    def pick_message(self):
        self.send_message(SERVER_PICK_UP)
        msg = self.get_message(CLIENT_MESSAGE_MAX_LENGTH)
        logging.info("Found message: '{}'".format(msg))

        return msg

    # Logout client
    def logout(self):
        self.send_message(SERVER_LOGOUT)
        logging.info("Logout client '{}'".format(self.ip))

    # Search every position inside destination square
    # expects start position at DESTINATION_SQUARE (top-left corner)
    # and try pick up the message, if message found logout client
    def search_square(self, start_direction):
        logging.info("Looking for message")

        self.turn_to_direction(start_direction, RIGHT)
        coords = DESTINATION_SQUARE
        direct = 0
        for _ in range(-2, 3):
            for i in range(-2, 3):
                if self.pick_message() != "":
                    logging.info("Message found")

                    self.logout()
                    return
                if i < 2:
                    coords = self.move_forward(coords)

            if direct == 0:
                self.turn_right()
                coords = self.move_forward(coords)
                self.turn_right()
                direct = 1
            else:
                self.turn_left()
                coords = self.move_forward(coords)
                self.turn_left()
                direct = 0

    # Main client function
    # authentications, find destination square, find message
    def run(self):
        logging.info("Starting communication with {}".format(self.ip))
        try:
            self.authenticate()
            self.find_and_search_square()

        except ServerLoginFailed as e:
            logging.warning(e)
            logging.error(SERVER_LOGIN_FAILED)
            self.send_message(SERVER_LOGIN_FAILED)
        except ServerSyntaxError as e:
            logging.warning(e)
            logging.error(SERVER_SYNTAX_ERROR)
            self.send_message(SERVER_SYNTAX_ERROR)
        except ServerLogicError as e:
            logging.warning(e)
            logging.error(SERVER_LOGIC_ERROR)
            self.send_message(SERVER_LOGIC_ERROR)
        except socket.timeout:
            logging.error("Timeout connection")
        finally:
            self.connection.close()
            logging.info("Closing connection with client at {}".format(self.ip))


class Server:
    def __init__(self, host_ip, port):
        self.ip = host_ip
        self.port = port
        self.clients = []

    def start(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.ip, self.port))
            logging.info("Socket binded to host_ip='{}' and port='{}'".format(HOST_IP, PORT))

            s.listen()
            logging.info("Socket is listening...")

            while True:
                try:
                    connection, (client_host_addr, client_port) = s.accept()
                except socket.timeout:
                    break
                connection.settimeout(TIMEOUT)
                logging.info("Connected to client ip='{}' and port='{}'".format(client_host_addr, client_port))

                client_conn = ClientConnection(connection, client_host_addr)
                self.clients.append(client_conn)
                client_conn.start()

            logging.info("Task finished, server can shutdown")
            s.close()

        self.shutdown()

    # not used
    def shutdown(self):
        (c.join() for c in self.clients)


def main():
    server = Server(HOST_IP, PORT)
    server.start()


if __name__ == '__main__':
    main()
