#!/usr/bin/python2
# -*- coding: utf-8 -*-

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""psutil is a cross-platform library for retrieving information on
running processes and system utilization (CPU, memory, disks, network)
in Python.
"""

from __future__ import division

__author__ = "Giampaolo Rodola'"
__version__ = "2.1.1"
version_info = tuple([int(num) for num in __version__.split('.')])

__all__ = [
    # exceptions
    "Error", "NoSuchProcess", "AccessDenied", "TimeoutExpired",
    # constants
    "version_info", "__version__",
    "STATUS_RUNNING", "STATUS_IDLE", "STATUS_SLEEPING", "STATUS_DISK_SLEEP",
    "STATUS_STOPPED", "STATUS_TRACING_STOP", "STATUS_ZOMBIE", "STATUS_DEAD",
    "STATUS_WAKING", "STATUS_LOCKED", "STATUS_WAITING", "STATUS_LOCKED",
    "CONN_ESTABLISHED", "CONN_SYN_SENT", "CONN_SYN_RECV", "CONN_FIN_WAIT1",
    "CONN_FIN_WAIT2", "CONN_TIME_WAIT", "CONN_CLOSE", "CONN_CLOSE_WAIT",
    "CONN_LAST_ACK", "CONN_LISTEN", "CONN_CLOSING", "CONN_NONE",
    # classes
    "Process", "Popen",
    # functions
    "pid_exists", "pids", "process_iter", "wait_procs",             # proc
    "virtual_memory", "swap_memory",                                # memory
    "cpu_times", "cpu_percent", "cpu_times_percent", "cpu_count",   # cpu
    "net_io_counters", "net_connections",                           # network
    "disk_io_counters", "disk_partitions", "disk_usage",            # disk
    "users", "boot_time",                                           # others
]

import sys
import os
import time
import signal
import warnings
import errno
from ambari_commons import subprocess32
try:
    import pwd
except ImportError:
    pwd = None

from psutil._common import memoize
from psutil._compat import property, callable, defaultdict
from psutil._compat import (wraps as _wraps,
                            PY3 as _PY3)
from psutil._common import (deprecated_method as _deprecated_method,
                            deprecated as _deprecated,
                            sdiskio as _nt_sys_diskio,
                            snetio as _nt_sys_netio)

from psutil._common import (STATUS_RUNNING,
                            STATUS_SLEEPING,
                            STATUS_DISK_SLEEP,
                            STATUS_STOPPED,
                            STATUS_TRACING_STOP,
                            STATUS_ZOMBIE,
                            STATUS_DEAD,
                            STATUS_WAKING,
                            STATUS_LOCKED,
                            STATUS_IDLE,  # bsd
                            STATUS_WAITING,  # bsd
                            STATUS_LOCKED)  # bsd

from psutil._common import (CONN_ESTABLISHED,
                            CONN_SYN_SENT,
                            CONN_SYN_RECV,
                            CONN_FIN_WAIT1,
                            CONN_FIN_WAIT2,
                            CONN_TIME_WAIT,
                            CONN_CLOSE,
                            CONN_CLOSE_WAIT,
                            CONN_LAST_ACK,
                            CONN_LISTEN,
                            CONN_CLOSING,
                            CONN_NONE)

if sys.platform.startswith("linux"):
    import psutil._pslinux as _psplatform
    from psutil._pslinux import (phymem_buffers,
                                 cached_phymem)

    from psutil._pslinux import (IOPRIO_CLASS_NONE,
                                 IOPRIO_CLASS_RT,
                                 IOPRIO_CLASS_BE,
                                 IOPRIO_CLASS_IDLE)
    # Linux >= 2.6.36
    if _psplatform.HAS_PRLIMIT:
        from _psutil_linux import (RLIM_INFINITY,
                                   RLIMIT_AS,
                                   RLIMIT_CORE,
                                   RLIMIT_CPU,
                                   RLIMIT_DATA,
                                   RLIMIT_FSIZE,
                                   RLIMIT_LOCKS,
                                   RLIMIT_MEMLOCK,
                                   RLIMIT_NOFILE,
                                   RLIMIT_NPROC,
                                   RLIMIT_RSS,
                                   RLIMIT_STACK)
        # Kinda ugly but considerably faster than using hasattr() and
        # setattr() against the module object (we are at import time:
        # speed matters).
        import _psutil_linux
        try:
            RLIMIT_MSGQUEUE = _psutil_linux.RLIMIT_MSGQUEUE
        except AttributeError:
            pass
        try:
            RLIMIT_NICE = _psutil_linux.RLIMIT_NICE
        except AttributeError:
            pass
        try:
            RLIMIT_RTPRIO = _psutil_linux.RLIMIT_RTPRIO
        except AttributeError:
            pass
        try:
            RLIMIT_RTTIME = _psutil_linux.RLIMIT_RTTIME
        except AttributeError:
            pass
        try:
            RLIMIT_SIGPENDING = _psutil_linux.RLIMIT_SIGPENDING
        except AttributeError:
            pass
        del _psutil_linux

elif sys.platform.startswith("win32"):
    import psutil._pswindows as _psplatform
    from _psutil_windows import (ABOVE_NORMAL_PRIORITY_CLASS,
                                 BELOW_NORMAL_PRIORITY_CLASS,
                                 HIGH_PRIORITY_CLASS,
                                 IDLE_PRIORITY_CLASS,
                                 NORMAL_PRIORITY_CLASS,
                                 REALTIME_PRIORITY_CLASS)
    from psutil._pswindows import CONN_DELETE_TCB

elif sys.platform.startswith("darwin"):
    import psutil._psosx as _psplatform

elif sys.platform.startswith("freebsd"):
    import psutil._psbsd as _psplatform

elif sys.platform.startswith("sunos"):
    import psutil._pssunos as _psplatform
    from psutil._pssunos import (CONN_IDLE,
                                 CONN_BOUND)

else:
    raise NotImplementedError('platform %s is not supported' % sys.platform)

__all__.extend(_psplatform.__extra__all__)


_TOTAL_PHYMEM = None
_POSIX = os.name == 'posix'
_WINDOWS = os.name == 'nt'
_timer = getattr(time, 'monotonic', time.time)


# =====================================================================
# --- exceptions
# =====================================================================

class Error(Exception):
    """Base exception class. All other psutil exceptions inherit
    from this one.
    """


class NoSuchProcess(Error):
    """Exception raised when a process with a certain PID doesn't
    or no longer exists (zombie).
    """

    def __init__(self, pid, name=None, msg=None):
        Error.__init__(self)
        self.pid = pid
        self.name = name
        self.msg = msg
        if msg is None:
            if name:
                details = "(pid=%s, name=%s)" % (self.pid, repr(self.name))
            else:
                details = "(pid=%s)" % self.pid
            self.msg = "process no longer exists " + details

    def __str__(self):
        return self.msg


class AccessDenied(Error):
    """Exception raised when permission to perform an action is denied."""

    def __init__(self, pid=None, name=None, msg=None):
        Error.__init__(self)
        self.pid = pid
        self.name = name
        self.msg = msg
        if msg is None:
            if (pid is not None) and (name is not None):
                self.msg = "(pid=%s, name=%s)" % (pid, repr(name))
            elif (pid is not None):
                self.msg = "(pid=%s)" % self.pid
            else:
                self.msg = ""

    def __str__(self):
        return self.msg


class TimeoutExpired(Error):
    """Raised on Process.wait(timeout) if timeout expires and process
    is still alive.
    """

    def __init__(self, seconds, pid=None, name=None):
        Error.__init__(self)
        self.seconds = seconds
        self.pid = pid
        self.name = name
        self.msg = "timeout after %s seconds" % seconds
        if (pid is not None) and (name is not None):
            self.msg += " (pid=%s, name=%s)" % (pid, repr(name))
        elif (pid is not None):
            self.msg += " (pid=%s)" % self.pid

    def __str__(self):
        return self.msg

# push exception classes into platform specific module namespace
_psplatform.NoSuchProcess = NoSuchProcess
_psplatform.AccessDenied = AccessDenied
_psplatform.TimeoutExpired = TimeoutExpired


# =====================================================================
# --- Process class
# =====================================================================

def _assert_pid_not_reused(fun):
    """Decorator which raises NoSuchProcess in case a process is no
    longer running or its PID has been reused.
    """
    @_wraps(fun)
    def wrapper(self, *args, **kwargs):
        if not self.is_running():
            raise NoSuchProcess(self.pid, self._name)
        return fun(self, *args, **kwargs)
    return wrapper


class Process(object):
    """Represents an OS process with the given PID.
    If PID is omitted current process PID (os.getpid()) is used.
    Raise NoSuchProcess if PID does not exist.

    Note that most of the methods of this class do not make sure
    the PID of the process being queried has been reused over time.
    That means you might end up retrieving an information referring
    to another process in case the original one this instance
    refers to is gone in the meantime.

    The only exceptions for which process identity is pre-emptively
    checked and guaranteed are:

     - parent()
     - children()
     - nice() (set)
     - ionice() (set)
     - rlimit() (set)
     - cpu_affinity (set)
     - suspend()
     - resume()
     - send_signal()
     - terminate()
     - kill()

    To prevent this problem for all other methods you can:
      - use is_running() before querying the process
      - if you're continuously iterating over a set of Process
        instances use process_iter() which pre-emptively checks
        process identity for every yielded instance
    """

    def __init__(self, pid=None):
        self._init(pid)

    def _init(self, pid, _ignore_nsp=False):
        if pid is None:
            pid = os.getpid()
        else:
            if not _PY3 and not isinstance(pid, (int, long)):
                raise TypeError('pid must be an integer (got %r)' % pid)
            if pid < 0:
                raise ValueError('pid must be a positive integer (got %s)'
                                 % pid)
        self._pid = pid
        self._name = None
        self._exe = None
        self._create_time = None
        self._gone = False
        self._hash = None
        # used for caching on Windows only (on POSIX ppid may change)
        self._ppid = None
        # platform-specific modules define an _psplatform.Process
        # implementation class
        self._proc = _psplatform.Process(pid)
        self._last_sys_cpu_times = None
        self._last_proc_cpu_times = None
        # cache creation time for later use in is_running() method
        try:
            self.create_time()
        except AccessDenied:
            # we should never get here as AFAIK we're able to get
            # process creation time on all platforms even as a
            # limited user
            pass
        except NoSuchProcess:
            if not _ignore_nsp:
                msg = 'no process found with pid %s' % pid
                raise NoSuchProcess(pid, None, msg)
            else:
                self._gone = True
        # This pair is supposed to indentify a Process instance
        # univocally over time (the PID alone is not enough as
        # it might refer to a process whose PID has been reused).
        # This will be used later in __eq__() and is_running().
        self._ident = (self.pid, self._create_time)

    def __str__(self):
        try:
            pid = self.pid
            name = repr(self.name())
        except NoSuchProcess:
            details = "(pid=%s (terminated))" % self.pid
        except AccessDenied:
            details = "(pid=%s)" % (self.pid)
        else:
            details = "(pid=%s, name=%s)" % (pid, name)
        return "%s.%s%s" % (self.__class__.__module__,
                            self.__class__.__name__, details)

    def __repr__(self):
        return "<%s at %s>" % (self.__str__(), id(self))

    def __eq__(self, other):
        # Test for equality with another Process object based
        # on PID and creation time.
        if not isinstance(other, Process):
            return NotImplemented
        return self._ident == other._ident

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        if self._hash is None:
            self._hash = hash(self._ident)
        return self._hash

    # --- utility methods

    def as_dict(self, attrs=[], ad_value=None):
        """Utility method returning process information as a
        hashable dictionary.

        If 'attrs' is specified it must be a list of strings
        reflecting available Process class' attribute names
        (e.g. ['cpu_times', 'name']) else all public (read
        only) attributes are assumed.

        'ad_value' is the value which gets assigned in case
        AccessDenied  exception is raised when retrieving that
        particular process information.
        """
        excluded_names = set(
            ['send_signal', 'suspend', 'resume', 'terminate', 'kill', 'wait',
             'is_running', 'as_dict', 'parent', 'children', 'rlimit'])
        retdict = dict()
        ls = set(attrs or [x for x in dir(self) if not x.startswith('get')])
        for name in ls:
            if name.startswith('_'):
                continue
            if name.startswith('set_'):
                continue
            if name.startswith('get_'):
                msg = "%s() is deprecated; use %s() instead" % (name, name[4:])
                warnings.warn(msg, category=DeprecationWarning, stacklevel=2)
                name = name[4:]
                if name in ls:
                    continue
            if name == 'getcwd':
                msg = "getcwd() is deprecated; use cwd() instead"
                warnings.warn(msg, category=DeprecationWarning, stacklevel=2)
                name = 'cwd'
                if name in ls:
                    continue

            if name in excluded_names:
                continue
            try:
                attr = getattr(self, name)
                if callable(attr):
                    ret = attr()
                else:
                    ret = attr
            except AccessDenied:
                ret = ad_value
            except NotImplementedError:
                # in case of not implemented functionality (may happen
                # on old or exotic systems) we want to crash only if
                # the user explicitly asked for that particular attr
                if attrs:
                    raise
                continue
            retdict[name] = ret
        return retdict

    def parent(self):
        """Return the parent process as a Process object pre-emptively
        checking whether PID has been reused.
        If no parent is known return None.
        """
        ppid = self.ppid()
        if ppid is not None:
            try:
                parent = Process(ppid)
                if parent.create_time() <= self.create_time():
                    return parent
                # ...else ppid has been reused by another process
            except NoSuchProcess:
                pass

    def is_running(self):
        """Return whether this process is running.
        It also checks if PID has been reused by another process in
        which case return False.
        """
        if self._gone:
            return False
        try:
            # Checking if PID is alive is not enough as the PID might
            # have been reused by another process: we also want to
            # check process identity.
            # Process identity / uniqueness over time is greanted by
            # (PID + creation time) and that is verified in __eq__.
            return self == Process(self.pid)
        except NoSuchProcess:
            self._gone = True
            return False

    # --- actual API

    @property
    def pid(self):
        """The process PID."""
        return self._pid

    def ppid(self):
        """The process parent PID.
        On Windows the return value is cached after first call.
        """
        # On POSIX we don't want to cache the ppid as it may unexpectedly
        # change to 1 (init) in case this process turns into a zombie:
        # https://code.google.com/p/psutil/issues/detail?id=321
        # http://stackoverflow.com/questions/356722/

        # XXX should we check creation time here rather than in
        # Process.parent()?
        if _POSIX:
            return self._proc.ppid()
        else:
            if self._ppid is None:
                self._ppid = self._proc.ppid()
            return self._ppid

    def name(self):
        """The process name. The return value is cached after first call."""
        if self._name is None:
            name = self._proc.name()
            if _POSIX and len(name) >= 15:
                # On UNIX the name gets truncated to the first 15 characters.
                # If it matches the first part of the cmdline we return that
                # one instead because it's usually more explicative.
                # Examples are "gnome-keyring-d" vs. "gnome-keyring-daemon".
                try:
                    cmdline = self.cmdline()
                except AccessDenied:
                    pass
                else:
                    if cmdline:
                        extended_name = os.path.basename(cmdline[0])
                        if extended_name.startswith(name):
                            name = extended_name
            self._proc._name = name
            self._name = name
        return self._name

    def exe(self):
        """The process executable as an absolute path.
        May also be an empty string.
        The return value is cached after first call.
        """
        def guess_it(fallback):
            # try to guess exe from cmdline[0] in absence of a native
            # exe representation
            cmdline = self.cmdline()
            if cmdline and hasattr(os, 'access') and hasattr(os, 'X_OK'):
                exe = cmdline[0]  # the possible exe
                # Attempt to guess only in case of an absolute path.
                # It is not safe otherwise as the process might have
                # changed cwd.
                if (os.path.isabs(exe)
                        and os.path.isfile(exe)
                        and os.access(exe, os.X_OK)):
                    return exe
            if isinstance(fallback, AccessDenied):
                raise fallback
            return fallback

        if self._exe is None:
            try:
                exe = self._proc.exe()
            except AccessDenied:
                err = sys.exc_info()[1]
                return guess_it(fallback=err)
            else:
                if not exe:
                    # underlying implementation can legitimately return an
                    # empty string; if that's the case we don't want to
                    # raise AD while guessing from the cmdline
                    try:
                        exe = guess_it(fallback=exe)
                    except AccessDenied:
                        pass
                self._exe = exe
        return self._exe

    def cmdline(self):
        """The command line this process has been called with."""
        return self._proc.cmdline()

    def status(self):
        """The process current status as a STATUS_* constant."""
        return self._proc.status()

    def username(self):
        """The name of the user that owns the process.
        On UNIX this is calculated by using *real* process uid.
        """
        if _POSIX:
            if pwd is None:
                # might happen if python was installed from sources
                raise ImportError(
                    "requires pwd module shipped with standard python")
            return pwd.getpwuid(self.uids().real).pw_name
        else:
            return self._proc.username()

    def create_time(self):
        """The process creation time as a floating point number
        expressed in seconds since the epoch, in UTC.
        The return value is cached after first call.
        """
        if self._create_time is None:
            self._create_time = self._proc.create_time()
        return self._create_time

    def cwd(self):
        """Process current working directory as an absolute path."""
        return self._proc.cwd()

    def nice(self, value=None):
        """Get or set process niceness (priority)."""
        if value is None:
            return self._proc.nice_get()
        else:
            if not self.is_running():
                raise NoSuchProcess(self.pid, self._name)
            self._proc.nice_set(value)

    if _POSIX:

        def uids(self):
            """Return process UIDs as a (real, effective, saved)
            namedtuple.
            """
            return self._proc.uids()

        def gids(self):
            """Return process GIDs as a (real, effective, saved)
            namedtuple.
            """
            return self._proc.gids()

        def terminal(self):
            """The terminal associated with this process, if any,
            else None.
            """
            return self._proc.terminal()

        def num_fds(self):
            """Return the number of file descriptors opened by this
            process (POSIX only).
            """
            return self._proc.num_fds()

    # Linux, BSD and Windows only
    if hasattr(_psplatform.Process, "io_counters"):

        def io_counters(self):
            """Return process I/O statistics as a
            (read_count, write_count, read_bytes, write_bytes)
            namedtuple.
            Those are the number of read/write calls performed and the
            amount of bytes read and written by the process.
            """
            return self._proc.io_counters()

    # Linux and Windows >= Vista only
    if hasattr(_psplatform.Process, "ionice_get"):

        def ionice(self, ioclass=None, value=None):
            """Get or set process I/O niceness (priority).

            On Linux 'ioclass' is one of the IOPRIO_CLASS_* constants.
            'value' is a number which goes from 0 to 7. The higher the
            value, the lower the I/O priority of the process.

            On Windows only 'ioclass' is used and it can be set to 2
            (normal), 1 (low) or 0 (very low).

            Available on Linux and Windows > Vista only.
            """
            if ioclass is None:
                if value is not None:
                    raise ValueError("'ioclass' must be specified")
                return self._proc.ionice_get()
            else:
                return self._proc.ionice_set(ioclass, value)

    # Linux only
    if hasattr(_psplatform.Process, "rlimit"):

        def rlimit(self, resource, limits=None):
            """Get or set process resource limits as a (soft, hard)
            tuple.

            'resource' is one of the RLIMIT_* constants.
            'limits' is supposed to be a (soft, hard)  tuple.

            See "man prlimit" for further info.
            Available on Linux only.
            """
            if limits is None:
                return self._proc.rlimit(resource)
            else:
                return self._proc.rlimit(resource, limits)

    # Windows and Linux only
    if hasattr(_psplatform.Process, "cpu_affinity_get"):

        def cpu_affinity(self, cpus=None):
            """Get or set process CPU affinity.
            If specified 'cpus' must be a list of CPUs for which you
            want to set the affinity (e.g. [0, 1]).
            """
            if cpus is None:
                return self._proc.cpu_affinity_get()
            else:
                self._proc.cpu_affinity_set(cpus)

    if _WINDOWS:

        def num_handles(self):
            """Return the number of handles opened by this process
            (Windows only).
            """
            return self._proc.num_handles()

    def num_ctx_switches(self):
        """Return the number of voluntary and involuntary context
        switches performed by this process.
        """
        return self._proc.num_ctx_switches()

    def num_threads(self):
        """Return the number of threads used by this process."""
        return self._proc.num_threads()

    def threads(self):
        """Return threads opened by process as a list of
        (id, user_time, system_time) namedtuples representing
        thread id and thread CPU times (user/system).
        """
        return self._proc.threads()

    @_assert_pid_not_reused
    def children(self, recursive=False):
        """Return the children of this process as a list of Process
        instances, pre-emptively checking whether PID has been reused.
        If recursive is True return all the parent descendants.

        Example (A == this process):

         A ─┐
            │
            ├─ B (child) ─┐
            │             └─ X (grandchild) ─┐
            │                                └─ Y (great grandchild)
            ├─ C (child)
            └─ D (child)

        >>> import psutil
        >>> p = psutil.Process()
        >>> p.children()
        B, C, D
        >>> p.children(recursive=True)
        B, X, Y, C, D

        Note that in the example above if process X disappears
        process Y won't be listed as the reference to process A
        is lost.
        """
        if hasattr(_psplatform, 'ppid_map'):
            # Windows only: obtain a {pid:ppid, ...} dict for all running
            # processes in one shot (faster).
            ppid_map = _psplatform.ppid_map()
        else:
            ppid_map = None

        ret = []
        if not recursive:
            if ppid_map is None:
                # 'slow' version, common to all platforms except Windows
                for p in process_iter():
                    try:
                        if p.ppid() == self.pid:
                            # if child happens to be older than its parent
                            # (self) it means child's PID has been reused
                            if self.create_time() <= p.create_time():
                                ret.append(p)
                    except NoSuchProcess:
                        pass
            else:
                # Windows only (faster)
                for pid, ppid in ppid_map.items():
                    if ppid == self.pid:
                        try:
                            child = Process(pid)
                            # if child happens to be older than its parent
                            # (self) it means child's PID has been reused
                            if self.create_time() <= child.create_time():
                                ret.append(child)
                        except NoSuchProcess:
                            pass
        else:
            # construct a dict where 'values' are all the processes
            # having 'key' as their parent
            table = defaultdict(list)
            if ppid_map is None:
                for p in process_iter():
                    try:
                        table[p.ppid()].append(p)
                    except NoSuchProcess:
                        pass
            else:
                for pid, ppid in ppid_map.items():
                    try:
                        p = Process(pid)
                        table[ppid].append(p)
                    except NoSuchProcess:
                        pass
            # At this point we have a mapping table where table[self.pid]
            # are the current process' children.
            # Below, we look for all descendants recursively, similarly
            # to a recursive function call.
            checkpids = [self.pid]
            for pid in checkpids:
                for child in table[pid]:
                    try:
                        # if child happens to be older than its parent
                        # (self) it means child's PID has been reused
                        intime = self.create_time() <= child.create_time()
                    except NoSuchProcess:
                        pass
                    else:
                        if intime:
                            ret.append(child)
                            if child.pid not in checkpids:
                                checkpids.append(child.pid)
        return ret

    def cpu_percent(self, interval=None):
        """Return a float representing the current process CPU
        utilization as a percentage.

        When interval is 0.0 or None (default) compares process times
        to system CPU times elapsed since last call, returning
        immediately (non-blocking). That means that the first time
        this is called it will return a meaningful 0.0 value.

        When interval is > 0.0 compares process times to system CPU
        times elapsed before and after the interval (blocking).

        In this case is recommended for accuracy that this function
        be called with at least 0.1 seconds between calls.

        Examples:

          >>> import psutil
          >>> p = psutil.Process(os.getpid())
          >>> # blocking
          >>> p.cpu_percent(interval=1)
          2.0
          >>> # non-blocking (percentage since last call)
          >>> p.cpu_percent(interval=None)
          2.9
          >>>
        """
        blocking = interval is not None and interval > 0.0
        num_cpus = cpu_count()
        if _POSIX:
            timer = lambda: _timer() * num_cpus
        else:
            timer = lambda: sum(cpu_times())
        if blocking:
            st1 = timer()
            pt1 = self._proc.cpu_times()
            time.sleep(interval)
            st2 = timer()
            pt2 = self._proc.cpu_times()
        else:
            st1 = self._last_sys_cpu_times
            pt1 = self._last_proc_cpu_times
            st2 = timer()
            pt2 = self._proc.cpu_times()
            if st1 is None or pt1 is None:
                self._last_sys_cpu_times = st2
                self._last_proc_cpu_times = pt2
                return 0.0

        delta_proc = (pt2.user - pt1.user) + (pt2.system - pt1.system)
        delta_time = st2 - st1
        # reset values for next call in case of interval == None
        self._last_sys_cpu_times = st2
        self._last_proc_cpu_times = pt2

        try:
            # The utilization split between all CPUs.
            # Note: a percentage > 100 is legitimate as it can result
            # from a process with multiple threads running on different
            # CPU cores, see:
            # http://stackoverflow.com/questions/1032357
            # https://code.google.com/p/psutil/issues/detail?id=474
            overall_percent = ((delta_proc / delta_time) * 100) * num_cpus
        except ZeroDivisionError:
            # interval was too low
            return 0.0
        else:
            return round(overall_percent, 1)

    def cpu_times(self):
        """Return a (user, system) namedtuple representing  the
        accumulated process time, in seconds.
        This is the same as os.times() but per-process.
        """
        return self._proc.cpu_times()

    def memory_info(self):
        """Return a tuple representing RSS (Resident Set Size) and VMS
        (Virtual Memory Size) in bytes.

        On UNIX RSS and VMS are the same values shown by 'ps'.

        On Windows RSS and VMS refer to "Mem Usage" and "VM Size"
        columns of taskmgr.exe.
        """
        return self._proc.memory_info()

    def memory_info_ex(self):
        """Return a namedtuple with variable fields depending on the
        platform representing extended memory information about
        this process. All numbers are expressed in bytes.
        """
        return self._proc.memory_info_ex()

    def memory_percent(self):
        """Compare physical system memory to process resident memory
        (RSS) and calculate process memory utilization as a percentage.
        """
        rss = self._proc.memory_info()[0]
        # use cached value if available
        total_phymem = _TOTAL_PHYMEM or virtual_memory().total
        try:
            return (rss / float(total_phymem)) * 100
        except ZeroDivisionError:
            return 0.0

    def memory_maps(self, grouped=True):
        """Return process' mapped memory regions as a list of nameduples
        whose fields are variable depending on the platform.

        If 'grouped' is True the mapped regions with the same 'path'
        are grouped together and the different memory fields are summed.

        If 'grouped' is False every mapped region is shown as a single
        entity and the namedtuple will also include the mapped region's
        address space ('addr') and permission set ('perms').
        """
        it = self._proc.memory_maps()
        if grouped:
            d = {}
            for tupl in it:
                path = tupl[2]
                nums = tupl[3:]
                try:
                    d[path] = map(lambda x, y: x + y, d[path], nums)
                except KeyError:
                    d[path] = nums
            nt = _psplatform.pmmap_grouped
            return [nt(path, *d[path]) for path in d]
        else:
            nt = _psplatform.pmmap_ext
            return [nt(*x) for x in it]

    def open_files(self):
        """Return files opened by process as a list of
        (path, fd) namedtuples including the absolute file name
        and file descriptor number.
        """
        return self._proc.open_files()

    def connections(self, kind='inet'):
        """Return connections opened by process as a list of
        (fd, family, type, laddr, raddr, status) namedtuples.
        The 'kind' parameter filters for connections that match the
        following criteria:

        Kind Value      Connections using
        inet            IPv4 and IPv6
        inet4           IPv4
        inet6           IPv6
        tcp             TCP
        tcp4            TCP over IPv4
        tcp6            TCP over IPv6
        udp             UDP
        udp4            UDP over IPv4
        udp6            UDP over IPv6
        unix            UNIX socket (both UDP and TCP protocols)
        all             the sum of all the possible families and protocols
        """
        return self._proc.connections(kind)

    if _POSIX:
        def _send_signal(self, sig):
            try:
                os.kill(self.pid, sig)
            except OSError:
                err = sys.exc_info()[1]
                if err.errno == errno.ESRCH:
                    self._gone = True
                    raise NoSuchProcess(self.pid, self._name)
                if err.errno == errno.EPERM:
                    raise AccessDenied(self.pid, self._name)
                raise

    @_assert_pid_not_reused
    def send_signal(self, sig):
        """Send a signal to process pre-emptively checking whether
        PID has been reused (see signal module constants) .
        On Windows only SIGTERM is valid and is treated as an alias
        for kill().
        """
        if _POSIX:
            self._send_signal(sig)
        else:
            if sig == signal.SIGTERM:
                self._proc.kill()
            else:
                raise ValueError("only SIGTERM is supported on Windows")

    @_assert_pid_not_reused
    def suspend(self):
        """Suspend process execution with SIGSTOP pre-emptively checking
        whether PID has been reused.
        On Windows this has the effect ot suspending all process threads.
        """
        if _POSIX:
            self._send_signal(signal.SIGSTOP)
        else:
            self._proc.suspend()

    @_assert_pid_not_reused
    def resume(self):
        """Resume process execution with SIGCONT pre-emptively checking
        whether PID has been reused.
        On Windows this has the effect of resuming all process threads.
        """
        if _POSIX:
            self._send_signal(signal.SIGCONT)
        else:
            self._proc.resume()

    @_assert_pid_not_reused
    def terminate(self):
        """Terminate the process with SIGTERM pre-emptively checking
        whether PID has been reused.
        On Windows this is an alias for kill().
        """
        if _POSIX:
            self._send_signal(signal.SIGTERM)
        else:
            self._proc.kill()

    @_assert_pid_not_reused
    def kill(self):
        """Kill the current process with SIGKILL pre-emptively checking
        whether PID has been reused.
        """
        if _POSIX:
            self._send_signal(signal.SIGKILL)
        else:
            self._proc.kill()

    def wait(self, timeout=None):
        """Wait for process to terminate and, if process is a children
        of os.getpid(), also return its exit code, else None.

        If the process is already terminated immediately return None
        instead of raising NoSuchProcess.

        If timeout (in seconds) is specified and process is still alive
        raise TimeoutExpired.

        To wait for multiple Process(es) use psutil.wait_procs().
        """
        if timeout is not None and not timeout >= 0:
            raise ValueError("timeout must be a positive integer")
        return self._proc.wait(timeout)

    # --- deprecated APIs

    _locals = set(locals())

    @_deprecated_method(replacement='children')
    def get_children(self):
        pass

    @_deprecated_method(replacement='connections')
    def get_connections(self):
        pass

    if "cpu_affinity" in _locals:
        @_deprecated_method(replacement='cpu_affinity')
        def get_cpu_affinity(self):
            pass

        @_deprecated_method(replacement='cpu_affinity')
        def set_cpu_affinity(self, cpus):
            pass

    @_deprecated_method(replacement='cpu_percent')
    def get_cpu_percent(self):
        pass

    @_deprecated_method(replacement='cpu_times')
    def get_cpu_times(self):
        pass

    @_deprecated_method(replacement='cwd')
    def getcwd(self):
        pass

    @_deprecated_method(replacement='memory_info_ex')
    def get_ext_memory_info(self):
        pass

    if "io_counters" in _locals:
        @_deprecated_method(replacement='io_counters')
        def get_io_counters(self):
            pass

    if "ionice" in _locals:
        @_deprecated_method(replacement='ionice')
        def get_ionice(self):
            pass

        @_deprecated_method(replacement='ionice')
        def set_ionice(self, ioclass, value=None):
            pass

    @_deprecated_method(replacement='memory_info')
    def get_memory_info(self):
        pass

    @_deprecated_method(replacement='memory_maps')
    def get_memory_maps(self):
        pass

    @_deprecated_method(replacement='memory_percent')
    def get_memory_percent(self):
        pass

    @_deprecated_method(replacement='nice')
    def get_nice(self):
        pass

    @_deprecated_method(replacement='num_ctx_switches')
    def get_num_ctx_switches(self):
        pass

    if 'num_fds' in _locals:
        @_deprecated_method(replacement='num_fds')
        def get_num_fds(self):
            pass

    if 'num_handles' in _locals:
        @_deprecated_method(replacement='num_handles')
        def get_num_handles(self):
            pass

    @_deprecated_method(replacement='num_threads')
    def get_num_threads(self):
        pass

    @_deprecated_method(replacement='open_files')
    def get_open_files(self):
        pass

    if "rlimit" in _locals:
        @_deprecated_method(replacement='rlimit')
        def get_rlimit(self):
            pass

        @_deprecated_method(replacement='rlimit')
        def set_rlimit(self, resource, limits):
            pass

    @_deprecated_method(replacement='threads')
    def get_threads(self):
        pass

    @_deprecated_method(replacement='nice')
    def set_nice(self, value):
        pass

    del _locals


# =====================================================================
# --- Popen class
# =====================================================================

class Popen(Process):
    """A more convenient interface to stdlib subprocess32 module.
    It starts a sub process and deals with it exactly as when using
    subprocess32.Popen class but in addition also provides all the
    properties and methods of psutil.Process class as a unified
    interface:

      >>> import psutil
      >>> from ambari_commons.subprocess32 import PIPE
      >>> p = psutil.Popen(["python", "-c", "print 'hi'"], stdout=PIPE)
      >>> p.name()
      'python'
      >>> p.uids()
      user(real=1000, effective=1000, saved=1000)
      >>> p.username()
      'giampaolo'
      >>> p.communicate()
      ('hi\n', None)
      >>> p.terminate()
      >>> p.wait(timeout=2)
      0
      >>>

    For method names common to both classes such as kill(), terminate()
    and wait(), psutil.Process implementation takes precedence.

    Unlike subprocess32.Popen this class pre-emptively checks wheter PID
    has been reused on send_signal(), terminate() and kill() so that
    you don't accidentally terminate another process, fixing
    http://bugs.python.org/issue6973.

    For a complete documentation refer to:
    http://docs.python.org/library/subprocess32.html
    """

    def __init__(self, *args, **kwargs):
        # Explicitly avoid to raise NoSuchProcess in case the process
        # spawned by subprocess32.Popen terminates too quickly, see:
        # https://code.google.com/p/psutil/issues/detail?id=193
        self.__subproc = subprocess32.Popen(*args, **kwargs)
        self._init(self.__subproc.pid, _ignore_nsp=True)

    def __dir__(self):
        return sorted(set(dir(Popen) + dir(subprocess32.Popen)))

    def __getattribute__(self, name):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            try:
                return object.__getattribute__(self.__subproc, name)
            except AttributeError:
                raise AttributeError("%s instance has no attribute '%s'"
                                     % (self.__class__.__name__, name))

    def wait(self, timeout=None):
        if self.__subproc.returncode is not None:
            return self.__subproc.returncode
        ret = super(Popen, self).wait(timeout)
        self.__subproc.returncode = ret
        return ret


# =====================================================================
# --- system processes related functions
# =====================================================================

def pids():
    """Return a list of current running PIDs."""
    return _psplatform.pids()


def pid_exists(pid):
    """Return True if given PID exists in the current process list.
    This is faster than doing "pid in psutil.pids()" and
    should be preferred.
    """
    if pid < 0:
        return False
    elif pid == 0 and _POSIX:
        # On POSIX we use os.kill() to determine PID existence.
        # According to "man 2 kill" PID 0 has a special meaning
        # though: it refers to <<every process in the process
        # group of the calling process>> and that is not we want
        # to do here.
        return pid in pids()
    else:
        return _psplatform.pid_exists(pid)


_pmap = {}

def process_iter():
    """Return a generator yielding a Process instance for all
    running processes.

    Every new Process instance is only created once and then cached
    into an internal table which is updated every time this is used.

    Cached Process instances are checked for identity so that you're
    safe in case a PID has been reused by another process, in which
    case the cached instance is updated.

    The sorting order in which processes are yielded is based on
    their PIDs.
    """
    def add(pid):
        proc = Process(pid)
        _pmap[proc.pid] = proc
        return proc

    def remove(pid):
        _pmap.pop(pid, None)

    a = set(pids())
    b = set(_pmap.keys())
    new_pids = a - b
    gone_pids = b - a

    for pid in gone_pids:
        remove(pid)
    for pid, proc in sorted(list(_pmap.items()) +
                            list(dict.fromkeys(new_pids).items())):
        try:
            if proc is None:  # new process
                yield add(pid)
            else:
                # use is_running() to check whether PID has been reused by
                # another process in which case yield a new Process instance
                if proc.is_running():
                    yield proc
                else:
                    yield add(pid)
        except NoSuchProcess:
            remove(pid)
        except AccessDenied:
            # Process creation time can't be determined hence there's
            # no way to tell whether the pid of the cached process
            # has been reused. Just return the cached version.
            yield proc


def wait_procs(procs, timeout=None, callback=None):
    """Convenience function which waits for a list of processes to
    terminate.

    Return a (gone, alive) tuple indicating which processes
    are gone and which ones are still alive.

    The gone ones will have a new 'returncode' attribute indicating
    process exit status (may be None).

    'callback' is a function which gets called every time a process
    terminates (a Process instance is passed as callback argument).

    Function will return as soon as all processes terminate or when
    timeout occurs.

    Typical use case is:

     - send SIGTERM to a list of processes
     - give them some time to terminate
     - send SIGKILL to those ones which are still alive

    Example:

    >>> def on_terminate(proc):
    ...     print("process {} terminated".format(proc))
    ...
    >>> for p in procs:
    ...    p.terminate()
    ...
    >>> gone, alive = wait_procs(procs, timeout=3, callback=on_terminate)
    >>> for p in alive:
    ...     p.kill()
    """
    def check_gone(proc, timeout):
        try:
            returncode = proc.wait(timeout=timeout)
        except TimeoutExpired:
            pass
        else:
            if returncode is not None or not proc.is_running():
                proc.returncode = returncode
                gone.add(proc)
                if callback is not None:
                    callback(proc)

    if timeout is not None and not timeout >= 0:
        msg = "timeout must be a positive integer, got %s" % timeout
        raise ValueError(msg)
    gone = set()
    alive = set(procs)
    if callback is not None and not callable(callback):
        raise TypeError("callback %r is not a callable" % callable)
    if timeout is not None:
        deadline = _timer() + timeout

    while alive:
        if timeout is not None and timeout <= 0:
            break
        for proc in alive:
            # Make sure that every complete iteration (all processes)
            # will last max 1 sec.
            # We do this because we don't want to wait too long on a
            # single process: in case it terminates too late other
            # processes may disappear in the meantime and their PID
            # reused.
            max_timeout = 1.0 / len(alive)
            if timeout is not None:
                timeout = min((deadline - _timer()), max_timeout)
                if timeout <= 0:
                    break
                check_gone(proc, timeout)
            else:
                check_gone(proc, max_timeout)
        alive = alive - gone

    if alive:
        # Last attempt over processes survived so far.
        # timeout == 0 won't make this function wait any further.
        for proc in alive:
            check_gone(proc, 0)
        alive = alive - gone

    return (list(gone), list(alive))


# =====================================================================
# --- CPU related functions
# =====================================================================

@memoize
def cpu_count(logical=True):
    """Return the number of logical CPUs in the system (same as
    os.cpu_count() in Python 3.4).

    If logical is False return the number of physical cores only
    (hyper thread CPUs are excluded).

    Return None if undetermined.

    The return value is cached after first call.
    If desired cache can be cleared like this:

    >>> psutil.cpu_count.cache_clear()
    """
    if logical:
        return _psplatform.cpu_count_logical()
    else:
        return _psplatform.cpu_count_physical()


def cpu_times(percpu=False):
    """Return system-wide CPU times as a namedtuple.
    Every CPU time represents the seconds the CPU has spent in the given mode.
    The namedtuple's fields availability varies depending on the platform:
     - user
     - system
     - idle
     - nice (UNIX)
     - iowait (Linux)
     - irq (Linux, FreeBSD)
     - softirq (Linux)
     - steal (Linux >= 2.6.11)
     - guest (Linux >= 2.6.24)
     - guest_nice (Linux >= 3.2.0)

    When percpu is True return a list of nameduples for each CPU.
    First element of the list refers to first CPU, second element
    to second CPU and so on.
    The order of the list is consistent across calls.
    """
    if not percpu:
        return _psplatform.cpu_times()
    else:
        return _psplatform.per_cpu_times()


_last_cpu_times = cpu_times()
_last_per_cpu_times = cpu_times(percpu=True)

def cpu_percent(interval=None, percpu=False):
    """Return a float representing the current system-wide CPU
    utilization as a percentage.

    When interval is > 0.0 compares system CPU times elapsed before
    and after the interval (blocking).

    When interval is 0.0 or None compares system CPU times elapsed
    since last call or module import, returning immediately (non
    blocking). That means the first time this is called it will
    return a meaningless 0.0 value which you should ignore.
    In this case is recommended for accuracy that this function be
    called with at least 0.1 seconds between calls.

    When percpu is True returns a list of floats representing the
    utilization as a percentage for each CPU.
    First element of the list refers to first CPU, second element
    to second CPU and so on.
    The order of the list is consistent across calls.

    Examples:

      >>> # blocking, system-wide
      >>> psutil.cpu_percent(interval=1)
      2.0
      >>>
      >>> # blocking, per-cpu
      >>> psutil.cpu_percent(interval=1, percpu=True)
      [2.0, 1.0]
      >>>
      >>> # non-blocking (percentage since last call)
      >>> psutil.cpu_percent(interval=None)
      2.9
      >>>
    """
    global _last_cpu_times
    global _last_per_cpu_times
    blocking = interval is not None and interval > 0.0

    def calculate(t1, t2):
        t1_all = sum(t1)
        t1_busy = t1_all - t1.idle

        t2_all = sum(t2)
        t2_busy = t2_all - t2.idle

        # this usually indicates a float precision issue
        if t2_busy <= t1_busy:
            return 0.0

        busy_delta = t2_busy - t1_busy
        all_delta = t2_all - t1_all
        busy_perc = (busy_delta / all_delta) * 100
        return round(busy_perc, 1)

    # system-wide usage
    if not percpu:
        if blocking:
            t1 = cpu_times()
            time.sleep(interval)
        else:
            t1 = _last_cpu_times
        _last_cpu_times = cpu_times()
        return calculate(t1, _last_cpu_times)
    # per-cpu usage
    else:
        ret = []
        if blocking:
            tot1 = cpu_times(percpu=True)
            time.sleep(interval)
        else:
            tot1 = _last_per_cpu_times
        _last_per_cpu_times = cpu_times(percpu=True)
        for t1, t2 in zip(tot1, _last_per_cpu_times):
            ret.append(calculate(t1, t2))
        return ret


# Use separate global vars for cpu_times_percent() so that it's
# independent from cpu_percent() and they can both be used within
# the same program.
_last_cpu_times_2 = _last_cpu_times
_last_per_cpu_times_2 = _last_per_cpu_times

def cpu_times_percent(interval=None, percpu=False):
    """Same as cpu_percent() but provides utilization percentages
    for each specific CPU time as is returned by cpu_times().
    For instance, on Linux we'll get:

      >>> cpu_times_percent()
      cpupercent(user=4.8, nice=0.0, system=4.8, idle=90.5, iowait=0.0,
                 irq=0.0, softirq=0.0, steal=0.0, guest=0.0, guest_nice=0.0)
      >>>

    interval and percpu arguments have the same meaning as in
    cpu_percent().
    """
    global _last_cpu_times_2
    global _last_per_cpu_times_2
    blocking = interval is not None and interval > 0.0

    def calculate(t1, t2):
        nums = []
        all_delta = sum(t2) - sum(t1)
        for field in t1._fields:
            field_delta = getattr(t2, field) - getattr(t1, field)
            try:
                field_perc = (100 * field_delta) / all_delta
            except ZeroDivisionError:
                field_perc = 0.0
            field_perc = round(field_perc, 1)
            if _WINDOWS:
                # XXX
                # Work around:
                # https://code.google.com/p/psutil/issues/detail?id=392
                # CPU times are always supposed to increase over time
                # or at least remain the same and that's because time
                # cannot go backwards.
                # Surprisingly sometimes this might not be the case on
                # Windows where 'system' CPU time can be smaller
                # compared to the previous call, resulting in corrupted
                # percentages (< 0 or > 100).
                # I really don't know what to do about that except
                # forcing the value to 0 or 100.
                if field_perc > 100.0:
                    field_perc = 100.0
                elif field_perc < 0.0:
                    field_perc = 0.0
            nums.append(field_perc)
        return _psplatform.scputimes(*nums)

    # system-wide usage
    if not percpu:
        if blocking:
            t1 = cpu_times()
            time.sleep(interval)
        else:
            t1 = _last_cpu_times_2
        _last_cpu_times_2 = cpu_times()
        return calculate(t1, _last_cpu_times_2)
    # per-cpu usage
    else:
        ret = []
        if blocking:
            tot1 = cpu_times(percpu=True)
            time.sleep(interval)
        else:
            tot1 = _last_per_cpu_times_2
        _last_per_cpu_times_2 = cpu_times(percpu=True)
        for t1, t2 in zip(tot1, _last_per_cpu_times_2):
            ret.append(calculate(t1, t2))
        return ret


# =====================================================================
# --- system memory related functions
# =====================================================================

def virtual_memory():
    """Return statistics about system memory usage as a namedtuple
    including the following fields, expressed in bytes:

     - total:
       total physical memory available.

     - available:
       the actual amount of available memory that can be given
       instantly to processes that request more memory in bytes; this
       is calculated by summing different memory values depending on
       the platform (e.g. free + buffers + cached on Linux) and it is
       supposed to be used to monitor actual memory usage in a cross
       platform fashion.

     - percent:
       the percentage usage calculated as (total - available) / total * 100

     - used:
       memory used, calculated differently depending on the platform and
       designed for informational purposes only:
        OSX: active + inactive + wired
        BSD: active + wired + cached
        LINUX: total - free

     - free:
       memory not being used at all (zeroed) that is readily available;
       note that this doesn't reflect the actual memory available
       (use 'available' instead)

    Platform-specific fields:

     - active (UNIX):
       memory currently in use or very recently used, and so it is in RAM.

     - inactive (UNIX):
       memory that is marked as not used.

     - buffers (BSD, Linux):
       cache for things like file system metadata.

     - cached (BSD, OSX):
       cache for various things.

     - wired (OSX, BSD):
       memory that is marked to always stay in RAM. It is never moved to disk.

     - shared (BSD):
       memory that may be simultaneously accessed by multiple processes.

    The sum of 'used' and 'available' does not necessarily equal total.
    On Windows 'available' and 'free' are the same.
    """
    global _TOTAL_PHYMEM
    ret = _psplatform.virtual_memory()
    # cached for later use in Process.memory_percent()
    _TOTAL_PHYMEM = ret.total
    return ret


def swap_memory():
    """Return system swap memory statistics as a namedtuple including
    the following fields:

     - total:   total swap memory in bytes
     - used:    used swap memory in bytes
     - free:    free swap memory in bytes
     - percent: the percentage usage
     - sin:     no. of bytes the system has swapped in from disk (cumulative)
     - sout:    no. of bytes the system has swapped out from disk (cumulative)

    'sin' and 'sout' on Windows are meaningless and always set to 0.
    """
    return _psplatform.swap_memory()


# =====================================================================
# --- disks/paritions related functions
# =====================================================================

def disk_usage(path):
    """Return disk usage statistics about the given path as a namedtuple
    including total, used and free space expressed in bytes plus the
    percentage usage.
    """
    return _psplatform.disk_usage(path)


def disk_partitions(all=False):
    """Return mounted partitions as a list of
    (device, mountpoint, fstype, opts) namedtuple.
    'opts' field is a raw string separated by commas indicating mount
    options which may vary depending on the platform.

    If "all" parameter is False return physical devices only and ignore
    all others.
    """
    return _psplatform.disk_partitions(all)


def disk_io_counters(perdisk=False):
    """Return system disk I/O statistics as a namedtuple including
    the following fields:

     - read_count:  number of reads
     - write_count: number of writes
     - read_bytes:  number of bytes read
     - write_bytes: number of bytes written
     - read_time:   time spent reading from disk (in milliseconds)
     - write_time:  time spent writing to disk (in milliseconds)

    If perdisk is True return the same information for every
    physical disk installed on the system as a dictionary
    with partition names as the keys and the namedutuple
    described above as the values.

    On recent Windows versions 'diskperf -y' command may need to be
    executed first otherwise this function won't find any disk.
    """
    rawdict = _psplatform.disk_io_counters()
    if not rawdict:
        raise RuntimeError("couldn't find any physical disk")
    if perdisk:
        for disk, fields in rawdict.items():
            rawdict[disk] = _nt_sys_diskio(*fields)
        return rawdict
    else:
        return _nt_sys_diskio(*[sum(x) for x in zip(*rawdict.values())])


# =====================================================================
# --- network related functions
# =====================================================================

def net_io_counters(pernic=False):
    """Return network I/O statistics as a namedtuple including
    the following fields:

     - bytes_sent:   number of bytes sent
     - bytes_recv:   number of bytes received
     - packets_sent: number of packets sent
     - packets_recv: number of packets received
     - errin:        total number of errors while receiving
     - errout:       total number of errors while sending
     - dropin:       total number of incoming packets which were dropped
     - dropout:      total number of outgoing packets which were dropped
                     (always 0 on OSX and BSD)

    If pernic is True return the same information for every
    network interface installed on the system as a dictionary
    with network interface names as the keys and the namedtuple
    described above as the values.
    """
    rawdict = _psplatform.net_io_counters()
    if not rawdict:
        raise RuntimeError("couldn't find any network interface")
    if pernic:
        for nic, fields in rawdict.items():
            rawdict[nic] = _nt_sys_netio(*fields)
        return rawdict
    else:
        return _nt_sys_netio(*[sum(x) for x in zip(*rawdict.values())])


def net_connections(kind='inet'):
    """Return system-wide connections as a list of
    (fd, family, type, laddr, raddr, status, pid) namedtuples.
    In case of limited privileges 'fd' and 'pid' may be set to -1
    and None respectively.
    The 'kind' parameter filters for connections that fit the
    following criteria:

    Kind Value      Connections using
    inet            IPv4 and IPv6
    inet4           IPv4
    inet6           IPv6
    tcp             TCP
    tcp4            TCP over IPv4
    tcp6            TCP over IPv6
    udp             UDP
    udp4            UDP over IPv4
    udp6            UDP over IPv6
    unix            UNIX socket (both UDP and TCP protocols)
    all             the sum of all the possible families and protocols
    """
    return _psplatform.net_connections(kind)

# =====================================================================
# --- other system related functions
# =====================================================================

def boot_time():
    """Return the system boot time expressed in seconds since the epoch.
    This is also available as psutil.BOOT_TIME.
    """
    # Note: we are not caching this because it is subject to
    # system clock updates.
    return _psplatform.boot_time()


def users():
    """Return users currently connected on the system as a list of
    namedtuples including the following fields.

     - user: the name of the user
     - terminal: the tty or pseudo-tty associated with the user, if any.
     - host: the host name associated with the entry, if any.
     - started: the creation time as a floating point number expressed in
       seconds since the epoch.
    """
    return _psplatform.users()


# =====================================================================
# --- deprecated functions
# =====================================================================

@_deprecated(replacement="psutil.pids()")
def get_pid_list():
    return pids()


@_deprecated(replacement="list(process_iter())")
def get_process_list():
    return list(process_iter())


@_deprecated(replacement="psutil.users()")
def get_users():
    return users()


@_deprecated(replacement="psutil.virtual_memory()")
def phymem_usage():
    """Return the amount of total, used and free physical memory
    on the system in bytes plus the percentage usage.
    Deprecated; use psutil.virtual_memory() instead.
    """
    return virtual_memory()


@_deprecated(replacement="psutil.swap_memory()")
def virtmem_usage():
    return swap_memory()


@_deprecated(replacement="psutil.phymem_usage().free")
def avail_phymem():
    return phymem_usage().free


@_deprecated(replacement="psutil.phymem_usage().used")
def used_phymem():
    return phymem_usage().used


@_deprecated(replacement="psutil.virtmem_usage().total")
def total_virtmem():
    return virtmem_usage().total


@_deprecated(replacement="psutil.virtmem_usage().used")
def used_virtmem():
    return virtmem_usage().used


@_deprecated(replacement="psutil.virtmem_usage().free")
def avail_virtmem():
    return virtmem_usage().free


@_deprecated(replacement="psutil.net_io_counters()")
def network_io_counters(pernic=False):
    return net_io_counters(pernic)


def test():
    """List info of all currently running processes emulating ps aux
    output.
    """
    import datetime
    from psutil._compat import print_

    today_day = datetime.date.today()
    templ = "%-10s %5s %4s %4s %7s %7s %-13s %5s %7s  %s"
    attrs = ['pid', 'cpu_percent', 'memory_percent', 'name', 'cpu_times',
             'create_time', 'memory_info']
    if _POSIX:
        attrs.append('uids')
        attrs.append('terminal')
    print_(templ % ("USER", "PID", "%CPU", "%MEM", "VSZ", "RSS", "TTY",
                    "START", "TIME", "COMMAND"))
    for p in process_iter():
        try:
            pinfo = p.as_dict(attrs, ad_value='')
        except NoSuchProcess:
            pass
        else:
            if pinfo['create_time']:
                ctime = datetime.datetime.fromtimestamp(pinfo['create_time'])
                if ctime.date() == today_day:
                    ctime = ctime.strftime("%H:%M")
                else:
                    ctime = ctime.strftime("%b%d")
            else:
                ctime = ''
            cputime = time.strftime("%M:%S",
                                    time.localtime(sum(pinfo['cpu_times'])))
            try:
                user = p.username()
            except KeyError:
                if _POSIX:
                    if pinfo['uids']:
                        user = str(pinfo['uids'].real)
                    else:
                        user = ''
                else:
                    raise
            except Error:
                user = ''
            if _WINDOWS and '\\' in user:
                user = user.split('\\')[1]
            vms = pinfo['memory_info'] and \
                int(pinfo['memory_info'].vms / 1024) or '?'
            rss = pinfo['memory_info'] and \
                int(pinfo['memory_info'].rss / 1024) or '?'
            memp = pinfo['memory_percent'] and \
                round(pinfo['memory_percent'], 1) or '?'
            print_(templ % (user[:10],
                            pinfo['pid'],
                            pinfo['cpu_percent'],
                            memp,
                            vms,
                            rss,
                            pinfo.get('terminal', '') or '?',
                            ctime,
                            cputime,
                            pinfo['name'].strip() or '?'))


def _replace_module():
    """Dirty hack to replace the module object in order to access
    deprecated module constants, see:
    http://www.dr-josiah.com/2013/12/properties-on-python-modules.html
    """
    class ModuleWrapper(object):

        def __repr__(self):
            return repr(self._module)
        __str__ = __repr__

        @property
        def NUM_CPUS(self):
            msg = "NUM_CPUS constant is deprecated; use cpu_count() instead"
            warnings.warn(msg, category=DeprecationWarning, stacklevel=2)
            return cpu_count()

        @property
        def BOOT_TIME(self):
            msg = "BOOT_TIME constant is deprecated; use boot_time() instead"
            warnings.warn(msg, category=DeprecationWarning, stacklevel=2)
            return boot_time()

        @property
        def TOTAL_PHYMEM(self):
            msg = "TOTAL_PHYMEM constant is deprecated; " \
                  "use virtual_memory().total instead"
            warnings.warn(msg, category=DeprecationWarning, stacklevel=2)
            return virtual_memory().total

    mod = ModuleWrapper()
    mod.__dict__ = globals()
    mod._module = sys.modules[__name__]
    sys.modules[__name__] = mod


_replace_module()
del property, memoize, division, _replace_module
if sys.version_info < (3, 0):
    del num

if __name__ == "__main__":
    test()
