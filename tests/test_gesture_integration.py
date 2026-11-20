from vision_engine.gesture_command_controller import GestureCommandController

controller = GestureCommandController()

controller.process('OPEN_PALM')
result = controller.process('FIST')
assert result['command'] == 'MINIMIZE_ALL', result
assert result['executed'], result

result = controller.process('FIST')
assert not result['executed'], result

controller.process('UNKNOWN')
result = controller.process('PEACE')
assert result['command'] == 'OPEN_VSCODE', result
assert result['executed'], result

result = controller.process('PEACE')
assert not result['executed'], result

print('INTEGRATION TEST: PASS')
print('MINIMIZE_ALL: PASS')
print('OPEN_VSCODE: PASS')
print('ONE-SHOT EXECUTION: PASS')
print('NEUTRAL RE-ARM: PASS')
