# Club Training v1.16.0

## No more mystery "could not start"

On a cold start (first run of the day, antivirus scanning the app) the
window could open before the app's internal server was ready, showing an
error page — and a genuine startup failure died silently. Now the app
waits up to 30 seconds and only opens the window once the server answers;
if something truly stops it starting (another program on its port, a
damaged database), a clear **"Club Training could not start"** dialog says
so, and the full detail is written to `logs\startup_error.log` in the app
folder — send that file if it ever happens again.

## Installing / upgrading

Download the zip, right-click → Properties → **Unblock**, extract, run
`Club Training.cmd`, and point "Install to" at your existing Club Training
folder — your database and backups are kept.
