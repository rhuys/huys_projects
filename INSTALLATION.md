# INSTALLATION AND USAGE INSTRUCTIONS

This page contains information on how to install on different platforms and usage

## Basic GIT actions

* *push* changes:
```
git add -A
git commit -m "commit message"
git push
```
* *pull* changes:  `git pull`
* *discard local changes* (before git pull)
```
git reset --hard HEAD
git clean -fd
```

# INSTALL PYTHON AND CREATE VENV

## On Windows

Note: do not use Powershell, but the regular command line. If Windows Terminal is opening PowerShell by default, you can make Command Prompt the default profile via: Windows Terminal → Settings → Startup → Default profile → Command Prompt.

1. Install python, for example, with anaconda
2. Create a virtual environment.  
```
cd `%USERPROFILE%\python
python -m venv 
```
To activate: `%USERPROFILE%\python\venv\Scripts\activate.bat`

## On Linux

Crate a venv in ~/python.  Make sure you use the latest python version!
`/bin/python3.12 -m venv venv`
To activate: `source ~/python/venv/bin/activate.csh`

Helper alias: add in `~/.cshrc.private`
```
alias pyenv 'source ~/python/venv/bin/activate.csh'
```
To activate, use `pyenv` first

## On Mac

Crate a venv in ~/python.  Make sure you use the latest python version!
`/bin/python3 -m venv venv`
To activate: `~/python/venv/bin/activate`

Helper alias: add in `~/.zprofile`
```
alias edit='open -a bbedit '
alias pyenv='source ~/python/venv/bin/activate'
```
To activate, use `pyenv` first


# REGISTER SSH KEY IN GITHUB

* Copy the entire contents of the private key: `cat ~/.ssh/id_rsa.pub`
* In Windows the location is `%USERPROFILE\.ssh\id_ed25519.pub`
* if this does not exist yet, create a public key by in a terminal/shell `ssh-keygen -t ed25519 -C "roeland.huys@imec.be"`
* Browse to `https://github.com/settings/keys`, [New SSH key], and copy the contents of the private key to the GIT site


# CLONE AND INSTALL

In the shell, go to `~/python` and do `git clone git@github.com:rhuys/<REPO>.git`
Activate the user profile
`cd <repo>`
`pip install -e .`

All path settings should be OK inside your venv.Í


# CONFIGURE VSCODE

We want VSCODE to use the VENV by default.
In VSCODE, **Ctrl+P -> Preferences: user settings (JSON)**
Add following lines:

```
    "python.defaultInterpreterPath": "${env:HOME}/python/venv/bin",  // my local VENV

    // prevent previous terminals to persist
    "terminal.integrated.hideOnStartup": "always",
    "terminal.integrated.enablePersistentSessions": false,
    "terminal.integrated.persistentSessionReviveProcess": "never",

    // make vscode always start venv
    "terminal.integrated.profiles.windows": {
        "Command Prompt": {
            "path": "C:\\Windows\\System32\\cmd.exe",∏
            "args": [ "/K", "C:\\Users\\huys100\\python\\venv\\Scripts\\activate.bat"
            ]
        }
    },
    "terminal.integrated.defaultProfile.windows": "Command Prompt",   // powershell is buggy on corparate machine
```
