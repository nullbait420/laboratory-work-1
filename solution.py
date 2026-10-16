import sys
import re

import os
import random
import math
import time

class Node:
    def __init__(self, value):
        self.value = value
        self.next = None


class Stack:
    def __init__(self):
        self._head = None
        self._size = 0

    def push(self, item):
        new_node = Node(item)
        new_node.next = self._head
        self._head = new_node
        self._size += 1

    def pop(self):
        if self.is_empty():
            return None
        pop_node = self._head
        self._head = self._head.next
        self._size -= 1
        return pop_node.value

    def top(self):
        if self.is_empty():
            return None
        return self._head.value

    def is_empty(self):
        return self._head is None

    def size(self):
        return self._size


class Processor:
    def __init__(self):
        self.user_stacks = {}
        self.global_stack = Stack()
        self.current_active = 0
        self.peak_active = 0
        self.peak_line = 0
        self.completed_sessions = 0
        self.total_duration = 0
        self.scan_errors = []
        self.eof_errors = []
        self.format_dialect = None
        self.username_regex = re.compile(r'^[A-Za-z0-9]+$')

    def process_line(self, line, line_number):
        line = line.strip()
        if not line:
            return

        tokens = line.split()
        
        if self.format_dialect is None:
            if len(tokens) in (2, 3):
                self.format_dialect = len(tokens)
            else:
                self.scan_errors.append(f'ERROR {line_number} bad_event')
                return

        if len(tokens) != self.format_dialect:
            self.scan_errors.append(f'ERROR {line_number} bad_event')
            return

        if self.format_dialect == 2:
            action, username = tokens
            timestamp = 0
        else:
            action, username, time_str = tokens
            if not time_str.isdigit():
                self.scan_errors.append(f'ERROR {line_number} bad_event')
                return
            timestamp = int(time_str)

        if action not in ('LOGIN', 'LOGOUT') or not self.username_regex.match(username):
            self.scan_errors.append(f'ERROR {line_number} bad_event')
            return

        if self.format_dialect == 2:
            if action == 'LOGIN':
                self.global_stack.push((username, line_number))
                self.current_active += 1
                if self.current_active > self.peak_active:
                    self.peak_active = self.current_active
                    self.peak_line = line_number
            elif action == 'LOGOUT':
                if self.global_stack.is_empty():
                    self.scan_errors.append(f'ERROR {line_number} logout_without_login')
                else:
                    top_user, opened_line = self.global_stack.top()
                    if top_user == username:
                        self.global_stack.pop()
                        self.completed_sessions += 1
                        self.current_active = max(0, self.current_active - 1)
                    else:
                        self.scan_errors.append(f'ERROR {line_number} order_violation')
        else:
            if action == 'LOGIN':
                if username not in self.user_stacks:
                    self.user_stacks[username] = Stack()
                self.user_stacks[username].push((line_number, timestamp))
                self.current_active += 1
                if self.current_active > self.peak_active:
                    self.peak_active = self.current_active
                    self.peak_line = line_number
            elif action == 'LOGOUT':
                if username in self.user_stacks and not self.user_stacks[username].is_empty():
                    opened_line, login_time = self.user_stacks[username].pop()
                    self.completed_sessions += 1
                    self.current_active = max(0, self.current_active - 1)
                    self.total_duration += (timestamp - login_time)
                else:
                    self.scan_errors.append(f'ERROR {line_number} logout_without_login')

    def finalize(self):
        all_unclosed = []
        if self.format_dialect == 2:
            while not self.global_stack.is_empty():
                username, opened_line = self.global_stack.pop()
                all_unclosed.append((opened_line, username))
        else:
            for username, stack in self.user_stacks.items():
                while not stack.is_empty():
                    opened_line, _ = stack.pop()
                    all_unclosed.append((opened_line, username))

        all_unclosed.sort(key=lambda x: x[0])
        for opened_line, username in all_unclosed:
            self.eof_errors.append(f'ERROR {opened_line} session_not_closed')

    def write_output_file(self, output_path):
        with open(output_path, 'w', encoding='utf-8') as file:
            for err in self.scan_errors:
                file.write(err + '\n')
            for err in self.eof_errors:
                file.write(err + '\n')
            file.write(f'SESSIONS {self.completed_sessions}\n')

    def print_statistics(self):
        print(f'Peak active sessions: {self.peak_active} (reached at line {self.peak_line})')
        if self.format_dialect == 3:
            if self.completed_sessions > 0:
                avg_duration = self.total_duration / self.completed_sessions
                print(f'Average session duration: {avg_duration:.2f}')
            else:
                print('Average session duration: undefined (0 completed sessions)')



def generate_bench_data(filepath, n_lines, dialect, seed):
    random.seed(seed)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    users = [f"user{i}" for i in range(300)]
    current_time = 1000

    with open(filepath, 'w', encoding='utf-8') as f:
        if dialect == 2:
            global_stack = []
            for _ in range(n_lines):
                current_time += random.randint(1, 10)
                if not global_stack or (len(global_stack) < n_lines//2 and random.random() > 0.4):
                    user = random.choice(users)
                    global_stack.append(user)
                    f.write(f"LOGIN {user}\n")
                else:
                    user = global_stack.pop()
                    f.write(f"LOGOUT {user}\n")
                    
            while global_stack:
                user = global_stack.pop()
                f.write(f"LOGOUT {user}\n")
        else:

            user_active_counts = {}
            
            for _ in range(n_lines):
                current_time += random.randint(1, 10)
                user = random.choice(users)

                if user_active_counts.get(user, 0) > 0 and random.random() > 0.5:
                    action = "LOGOUT"
                    user_active_counts[user] -= 1
                else:
                    action = "LOGIN"
                    user_active_counts[user] = user_active_counts.get(user, 0) + 1
                
                f.write(f"{action} {user} {current_time}\n")


def execute_single_measurement(input_path):
    processor = Processor()
    t0 = time.perf_counter()
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as file:
        for line_number, line in enumerate(file, start=1):
            processor.process_line(line, line_number)
    processor.finalize()
    dt = time.perf_counter() - t0
    
    return dt, processor.completed_sessions


def run_protocol_benchmark(seed, warmups, runs, dialect):
    #print("-" * 85)
    #print(f"Аргументы бенчмарка: сид: {seed}, прогревы: {warmups}, повторы: {runs}, диалект: {dialect}")
    #print("-" * 85)
 
    sizes = [2000, 4000, 8000, 16000, 32000, 64000]
    tmp_dir = ".bench_tmp"
    
    print(f"{'n':>8} | {'min, ms':>8} | {'max, ms':>8} | {'median, ms':>11} | {'average, ms':>11} | {'t / n':>13} | checksum")
    print("-" * 85)
    
    for n in sizes:
        inp_path = os.path.join(tmp_dir, f"bench_{n}.in")
        generate_bench_data(inp_path, n, dialect, seed)
        
        for _ in range(warmups):
            _, _ = execute_single_measurement(inp_path)
            
        durations = []
        total_checksum = 0
        for _ in range(runs):
            dt, sessions_count = execute_single_measurement(inp_path)
            durations.append(dt * 1000)  
            total_checksum += sessions_count
            
        durations.sort()
        min_ms = durations[0]
        max_ms = durations[-1]
        mean_ms = sum(durations) / len(durations)
        
        mid = len(durations) // 2
        if len(durations) % 2 != 0:
            median_ms = durations[mid]
        else:
            median_ms = (durations[mid - 1] + durations[mid]) / 2.0
            
        f_n = n
        ratio = median_ms / f_n * 1000  
        
        print(f"{n:>8} | {min_ms:>8.2f} | {max_ms:>8.2f} | {median_ms:>11.2f} | {mean_ms:>11.2f} | {ratio:>13.4f} | {total_checksum}")
        

def main():
    if "--bench" in sys.argv:
        seed = 1
        warmups = 3
        runs = 10
        dialect = 3
        
        if "--seed" in sys.argv:
            seed = int(sys.argv[sys.argv.index("--seed") + 1])
        if "--warmups" in sys.argv:
            warmups = max(3, int(sys.argv[sys.argv.index("--warmups") + 1]))
        if "--runs" in sys.argv:
            runs = max(7, int(sys.argv[sys.argv.index("--runs") + 1]))
        if "--dialect" in sys.argv:
            dialect = int(sys.argv[sys.argv.index("--dialect") + 1])
            
        run_protocol_benchmark(seed, warmups, runs, dialect)
        sys.exit(0)

    if len(sys.argv) != 3:
        print("Стандартный режим: python solution.py <вход.in> <выход.out>")
        print("Режим бенчмарка:   python solution.py --bench [--seed 1] [--warmups 3] [--runs 10] [--dialect 3]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    processor = Processor()

    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as file:
            for line_number, line in enumerate(file, start=1):
                processor.process_line(line, line_number)
    except Exception:
        sys.exit(1)
            
    processor.finalize()
    processor.write_output_file(output_path)
    processor.print_statistics()


if __name__ == '__main__':
    main()
