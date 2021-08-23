from termcolor import colored
def highlight(str, color='red'):
    return colored(str, color, attrs=['bold'])