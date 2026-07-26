import sys
sys.path.insert(0, '.')
from context_manager.context_manager import ContextManager
from context_manager.clarification_engine import ClarificationType
from unittest import mock
from context_manager.app_detector import AppStatus, WindowState

cm = ContextManager()

# Test 1: open Chrome (not running) => no clarification
with mock.patch('context_manager.app_detector.AppDetector.detect') as md:
    md.return_value = AppStatus(process_name='chrome.exe', display_name='Chrome', running=False, windows=[])
    r = cm.check_before_execution('open_app', {'app_name': 'chrome', 'original_app': 'Chrome'}, 'open Chrome')
    assert r is None, f'Expected None, got {r}'
    print('PASS: Chrome not running -> no clarification')

# Test 2: open Chrome (running, not focused) => asks switch/new
with mock.patch('context_manager.app_detector.AppDetector.detect') as md:
    md.return_value = AppStatus(process_name='chrome.exe', display_name='Chrome', running=True, windows=[
        WindowState(hwnd=1, title='Chrome', pid=100, is_minimized=False, is_maximized=True, is_focused=False, is_visible=True)])
    r = cm.check_before_execution('open_app', {'app_name': 'chrome', 'original_app': 'Chrome'}, 'open Chrome')
    assert r is not None and r.needs_clarification, 'Expected clarification'
    assert 'already running' in r.clarification_question, f'Unexpected: {r.clarification_question}'
    print(f'PASS: Chrome running -> "{r.clarification_question}"')

# Test 3: resolve 'switch to it' => action
r2 = cm.handle_follow_up('switch to it')
assert r2 is not None and r2.success, f'Expected success, got {r2}'
assert r2.data['action'] == 'switch_to_existing'
print(f'PASS: Resolve "switch to it" -> {r2.data["action"]}')

# Test 4: resolve 'new window'
cm.clarification.set_pending('question', ClarificationType.APP_ALREADY_RUNNING, {'app_name': 'chrome'})
r3 = cm.handle_follow_up('new window')
assert r3 is not None and r3.success
assert r3.data['action'] == 'open_new_window'
print(f'PASS: Resolve "new window" -> {r3.data["action"]}')

# Test 5: resolve 'yes' => switch
cm.clarification.set_pending('question', ClarificationType.APP_ALREADY_RUNNING, {'app_name': 'notepad'})
r4 = cm.handle_follow_up('yes')
assert r4 is not None and r4.success
assert r4.data['action'] == 'switch_to_existing'
print(f'PASS: Resolve "yes" -> {r4.data["action"]}')

# Test 6: resolve 'no' => open new
cm.clarification.set_pending('question', ClarificationType.APP_ALREADY_RUNNING, {'app_name': 'notepad'})
r5 = cm.handle_follow_up('no')
assert r5 is not None and r5.success
assert r5.data['action'] == 'open_new_window'
print(f'PASS: Resolve "no" -> {r5.data["action"]}')

print()
print('All sanity checks PASSED')
