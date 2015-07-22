#emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
#ex: set sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See the COPYING file distributed along with the smile package for the
#   copyright and license terms.
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##

from contextlib import contextmanager
import inspect

import kivy_overrides
import random
from ref import Ref, val
from utils import rindex, get_class_name
from log import dump
from clock import clock


class RunOnEnter():
    """Inherited class to indicate to a state that it should run
    immediately upon entering the state (instead of waiting until the
    state time specified by the parent). This ensures that parent
    states do not disturb the timing of their children.
    """
    pass


class State(object):
    """
    Base State object for the hierarchical state machine.

    Provides framework for entering, processing, and leaving states.

    Subclasses can customize behavior by implementing the _enter,
    _callback, and _leave methods.

    Parameters
    ----------
    interval : {0, -1, float}
        The number of seconds between each call, 0 means once, 
        -1 means every frame.
    parent : {None, ``ParentState``}
        Parent state to attach to. Will search for experiment if None.
    duration : {0.0, float}
        Duration of the state.
    save_log : bool
        Whether the state logs itself.
    
    """
    def __init__(self, interval=0, parent=None, duration=0.0, 
                 save_log=True, auto_finalize=True, name=None):
        """
        """
        self.state_time = None
        self.start_time = None
        self.end_time = None
        self.enter_time = None
        self.leave_time = None
        self.first_call_time = None
        self.first_call_error = None
        self.last_call_time = None
        self.last_call_error = None
        self.interval = interval
        self.raw_duration = duration
        self.duration = 0.0
        self.parent = parent
        self.active = False
        self.following_may_run = False
        self.save_log = save_log
        self.auto_finalize = auto_finalize
        self.name = name

        # get instantiation context
        base_inits = {}
        for base in inspect.getmro(type(self)):
            if base is not object and hasattr(base, "__init__"):
                init = base.__init__
                filename = inspect.getsourcefile(init)
                lines, start_lineno = inspect.getsourcelines(init)
                base_inits.setdefault(filename, []).extend(
                    range(start_lineno, start_lineno + len(lines)))
        for (frame, filename, lineno,
             function, code_context, index) in inspect.stack():
            if filename in base_inits and lineno in base_inits[filename]:
                continue
            self.instantiation_filename = filename
            self.instantiation_lineno = lineno
            break
        else:
            raise RuntimeError(
                "Can't figure out where instantiation took place!")  #!!!!!!!!!

        # get the exp reference
        from experiment import Experiment
        try:
            self.exp = Experiment.last_instance()
        except AttributeError:
            self.exp = None

        # try and set the current parent
        if self.parent is None and not self.exp is None:
            # try and get it from the exp
            self.parent = self.exp._parents[-1]

        # add self to children if we have a parent
        if self.parent:
            # append to children
            self.parent.children.append(self)

        # start the log
        self.state = self.__class__.__name__
        self.log_attrs = ['state', 'state_time', 'start_time', 'end_time',
                          'enter_time', 'leave_time',
                          'first_call_time', 'first_call_error',
                          'last_call_time', 'last_call_error',
                          'duration']

    def print_trace(self, child=None, t=None):
        if t is None:
            t = clock.now()
        if self.parent is None:
            print " SMILE Trace:"
        else:
            self.parent.print_trace(self, t)
        if self.name is None:
            name_spec = ""
        else:
            name_spec = " (%s)" % self.name
        def tstr(tm):
            if (isinstance(tm, dict) and
                len(tm) == 2 and
                "time" in tm and "error" in tm):
                error = ", error=%fs" % tm["error"]
                tm = tm["time"]
            else:
                error = ""
            if type(tm) not in (float, int):
                return repr(tm)
            offset = t - tm
            if offset < 0.0:
                return "%fs from now%s" % (-offset, error)
            else:
                return "%fs ago%s" % (offset, error)
        print "   %s%s - file: %s, line: %d" % (
            type(self).__name__,
            name_spec,
            self.instantiation_filename,
            self.instantiation_lineno)
        for attr_name in self.log_attrs:
            value = val(getattr(self, attr_name))
            if attr_name.endswith("_time"):
                print "     %s: %s" % (attr_name, tstr(value))
            else:
                print "     %s: %r" % (attr_name, value)

    def claim_exceptions(self):
        if self.exp is not None:
            self.exp.current_state = self

    def get_log(self):
    	"""
        Evaluate all the log attributes and generate a dict.
        """
        
        keyvals = [(a,val(getattr(self,a))) if hasattr(self,a) 
                   else (a,None) for a in self.log_attrs]
        return dict(keyvals)

    def get_log_stream(self):
    	"""
    	Gets log stream for the current experiment
    	"""
        if self.exp is None:
            return None
        else:
            return self.exp.state_log_stream
        
    def __getitem__(self, index):
    	"""
    	Returns a reference object for the specified attribute.
    	"""
        if hasattr(self, index):
            return Ref(self, index)
        else:
            class_name = get_class_name(self)[0]
            raise ValueError('%s state does not have attribute "%s".' % 
                             (class_name, index))

    # PBS: Must eventually check for specific attrs for this to work
    #def __getattribute__(self, name):
    #    return Ref(self, name)

    def _callback(self):
        # Subclasses of State must implement the callback.
        pass
        
    def callback(self):
    	"""
    	Run at the scheduled state time.
    	"""
        self.claim_exceptions()
        self.last_call_time = clock.now()
        self.last_call_error = self.last_call_time - self.state_time
        if self.first_call_time is None:
            self.first_call_time = self.last_call_time
            self.first_call_error = self.last_call_error

        # call the user-defined callback
        self._callback()

        # see if done
        if self.interval == 0:
            # we're done
            self.leave()

    def get_parent_state_time(self):
    	"""
    	Returns state time for the parent. If no parent, logs current time. 
    	"""
        if self.parent:
            return self.parent.get_state_time()
        else:
            return clock.now()

    def _enter(self):
        pass

    def enter(self):
        """
        Gets the starting time from the parent state
        """
        self.claim_exceptions()
        self.state_time = self.get_parent_state_time()
        self.start_time = self.state_time
        self.enter_time = clock.now()
        self.leave_time = None
        self.end_time = None

        # add the callback to the schedule
        if issubclass(self.__class__,RunOnEnter):
            # parents states (and states like Logging) run immediately
            event_time = None
        else:
            event_time = self.start_time
        if self.interval < 0:
            # schedule it for every event loop
            clock.schedule(self.callback, event_time=event_time,
                           repeat_interval=0)
        elif self.interval == 0:
            # schedule the interval (0 means once)
            clock.schedule(self.callback, event_time=event_time)
        else:
            # schedule the interval
            clock.schedule(self.callback, event_time=event_time,
                           repeat_interval=self.interval)

        # say we're active
        self.active = True
        self.following_may_run = False

        if self.parent:
            self.parent.child_enter_callback(self)  #TODO: queued call?

        # if we don't have the exp reference, get it now
        if self.exp is None:
            from experiment import Experiment
            self.exp = Experiment.last_instance()

        # compute the duration
        self.duration = val(self.raw_duration)

        if self.duration > 0:
            self.end_time = self.start_time + self.duration
            
        # custom enter code
        self._enter()

    def _leave(self):
        pass

    def leave(self):
        """
        Gets the end time of the state (logs current time)
        """
        # ignore leave call if not active
        if not self.active:
            return

        self.claim_exceptions()

        self.leave_time = clock.now()

        # remove the callback from the schedule
        clock.unschedule(self.callback)

        self.set_end_time()

        self.following_may_run = True
        if self.parent:
            self.parent.child_leave_callback(self)  #TODO: queued call?

        # call custom leave code
        self._leave()

        if self.auto_finalize:
            self.finalize()

    def cancel(self):
        self.leave()

    def finalize(self):
        self.active = False
        if self.save_log:
            dump([self.get_log()],self.get_log_stream())
        if self.parent:
            self.parent.child_finalize_callback(self)  #TODO: queued call?

    def set_end_time(self):
        if self.duration < 0:
            self.end_time = self.leave_time
        else:
            self.end_time = self.start_time + self.duration


class ParentState(State, RunOnEnter):
    """
    Base state for parents that can hold children states. 

    Only parent states can contain other states.

    Implicit hierarchies can be generated using the `with` syntax.
    
    Parameters
    ----------
    children: object
    	Children States (objects) contained within the Parent State
    parent: object
    	Parent state object
    duration: float
    	Duration of the parent state. An interval of 0 means enter the state once, 
    	-1 means every frame.
    	Defaults to -1
    save_log: bool
        If set to 'True,' details about the parent state will be automatically saved 
        in the log files.

    """
    def __init__(self, children=None, parent=None, duration=-1, save_log=True,
                 name=None):
        super(ParentState, self).__init__(interval=-1, parent=parent, 
                                          duration=duration, 
                                          save_log=save_log,
                                          auto_finalize=False,
                                          name=name)
        # process children
        if children is None:
            children = []
        self.children = []
        for c in children:
            self.claim_child(c)
        
        self.unfinalized_children = set()

    def get_state_time(self):
        return self.state_time

    def claim_child(self, child):
        if not child.parent is None:
            child.parent.children.remove(child)
        child.parent = self
        self.children.append(child)

    def child_enter_callback(self, child):
        #print "Entered child %r (%r) of parent %r (%r)." % (child, child.name, self, self.name)  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        self.unfinalized_children.add(child)

    def child_leave_callback(self, child):
        pass

    def child_finalize_callback(self, child):
        #print "Finalized child %r (%r) of parent %r (%r)." % (child, child.name, self, self.name)  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        self.unfinalized_children.discard(child)
        if self.following_may_run and not len(self.unfinalized_children):
            self.finalize()

    def _enter(self):
        self.unfinalized_children = set()

    def _leave(self):
        if not len(self.unfinalized_children):
            self.finalize()

    def cancel(self):
        super(ParentState, self).cancel()
        for c in self.children:
            c.cancel()

    def __enter__(self):
        # push self as current parent
        if not self.exp is None:
            self.exp._parents.append(self)
        return self

    def __exit__(self, type, value, tb):
        # pop self off
        if not self.exp is None:
            state = self.exp._parents.pop()


class Parallel(ParentState):
    """
    Parent state that runs its children in parallel.

    A Parallel Parent State is done when all its children have
    finished.
    
    """
    def __init__(self, *pargs, **kwargs):
        super(Parallel, self).__init__(*pargs, **kwargs)
        self.children_blocking = []

    def print_trace(self, child=None, t=None):
        super(Parallel, self).print_trace(child, t)
        self._normalize_children_blocking()
        if self.children_blocking[self.children.index(child)]:
            print "     Blocking child..."
        else:
            print "     Non-blocking child..."

    def _normalize_children_blocking(self):
        for _n in range(len(self.children_blocking), len(self.children)):
            self.children_blocking.append(True)

    def set_child_blocking(self, n, blocking):
        self._normalize_children_blocking()
        self.children_blocking[n] = blocking

    def _enter(self):
        super(Parallel, self)._enter()
        self._normalize_children_blocking()
        self.blocking_children = [c for c, blocking in
                                  zip(self.children, self.children_blocking) if
                                  blocking]
        self.blocking_remaining = self.blocking_children[:]
        if len(self.children):
            for c in self.children:
                c.enter()  #TODO: queued call?
        else:
            self.leave()
            self.finalize()

    def child_leave_callback(self, child):
        super(Parallel, self).child_leave_callback(child)
        try:
            self.blocking_remaining.remove(child)
        except ValueError:
            return
        if not len(self.blocking_remaining):
            # we're done
            self.leave()

    def _leave(self):
        for c in self.children:
            c.cancel()

    def set_end_time(self):
        self.end_time = max([c.end_time for c in self.blocking_children])


def _get_calling_context(d):
    frame, filename, lineno, function, code_context, index = inspect.stack()[d]
    return filename, lineno


@contextmanager
def Meanwhile(name=None):
    # get the exp reference
    from experiment import Experiment
    try:
        exp = Experiment.last_instance()
    except AttributeError:
        raise AttributeError("You must first instantiate an Experiment.")

    # find the parent
    parent = exp._parents[-1]

    # find the previous child state (-1 because this is not a state)
    prev_state = parent.children[-1]

    # build the new Parallel state
    filename, lineno = _get_calling_context(3)
    with Parallel() as p:
        p.instantiation_filename = filename
        p.instantiation_lineno = lineno
        with Serial(name=name) as s:
            s.instantiation_filename = filename
            s.instantiation_lineno = lineno
            yield p
    p.claim_child(prev_state)
    p.set_child_blocking(0, False)

@contextmanager
def UntilDone(name=None):
    # get the exp reference
    from experiment import Experiment
    try:
        exp = Experiment.last_instance()
    except AttributeError:
        raise AttributeError("You must first instantiate an Experiment.")

    # find the parent
    parent = exp._parents[-1]

    # find the previous child state (-1 because this is not a state)
    prev_state = parent.children[-1]

    # build the new Parallel state
    filename, lineno = _get_calling_context(3)
    with Parallel() as p:
        p.instantiation_filename = filename
        p.instantiation_lineno = lineno
        with Serial(name=name) as s:
            s.instantiation_filename = filename
            s.instantiation_lineno = lineno
            yield p
    p.claim_child(prev_state)
    p.set_child_blocking(1, False)


class Serial(ParentState):
    """Parent state that runs its children in serial.

    A Serial Parent State is done when the last state in the chain is
    finished.
    
    """
    def _enter(self):
        super(Serial, self)._enter()
        self.child_iterator = iter(self.children)
        self.current_child = None
        try:
            self.current_child = self.child_iterator.next()
            self.current_child.enter()  #TODO: queued call?
        except StopIteration:
            self.leave()
            self.finalize()

    def child_leave_callback(self, child):
        super(Serial, self).child_leave_callback(child)
        self.state_time = self.current_child.end_time
        try:
            self.current_child = self.child_iterator.next()
            #TODO: use clone of state instead!
            if self.current_child.active:
                dagdafgsdf
            if not self.current_child.active:
                self.current_child.enter()  #TODO: queued call?
        except StopIteration:
            self.leave()

    #def child_finalize_callback(self, child):
    #    super(Serial, self).child_finalize_callback(child)
    #    if child is self.current_child:
    #        self.current_child.enter()

    def set_end_time(self):
        if self.current_child is None:
            self.end_time = self.start_time
        else:
            self.end_time = self.current_child.end_time

    
class If(ParentState):
    """
    Parent state to implement conditional branching. If state is used in lieu
    of a traditional Python if statement.
    
    Creates true and false states based on a specified conditional.
    
    Parameters
    ----------
    conditional: bool
    	Boolean statement that determines a true and false state
    true_state: object
    	State to enter if conditional evaluates to True
    false_state: object
    	State to enter if conditional evaluates to False
    parent: object
    	The parent state containing the If object
    save_log: bool
    	If set to 'True,' details about the If state will be automatically saved 
    	in the log files.
    
    Examples
    --------
    key = KeyResponse(['Y','N'])
    If((key['rt']>2.0)&(key['resp'] != None), stateA, stateB)
    
    State A is entered if conditional evaluates to True
    State B is entered if conditional evaluates to False

    True and false states are automatically created if they are not
    passed in.  This allows for the more natural use of the If state 
    as follows:

    with If((key['rt']>2.0)&(key['resp'] != None)):
        # fill the true state
        pass
    with Else():
        # fill the false state
        pass
    
    Log Parameters
    --------------
    outcome : outcome of the conditional evaluation. Appended to state.yaml
        and state.csv

    """
    def __init__(self, conditional, true_state=None, false_state=None, 
                 parent=None, save_log=True, name=None):

        # init the parent class
        super(If, self).__init__(parent=parent, duration=-1, 
                                 save_log=save_log, name=name)

        # save a list of conds to be evaluated (last one always True, acts as the Else)
        self.cond = [conditional, True]
        self.outcome = None
        self.true_state = true_state
        self.false_state = false_state

        if self.true_state:
            # make sure to set this as the parent of the true state
            self.claim_child(self.true_state)
        else:
            # create the true state
            self.true_state = Serial(parent=self, name="IF BODY")
            self.true_state.instantiation_filename = self.instantiation_filename
            self.true_state.instantiation_lineno = self.instantiation_lineno

        # process the false state similarly
        if self.false_state:
            self.claim_child(self.false_state)
        else:
            # create the false state
            self.false_state = Serial(parent=self, name="FALSE STATE")
            self.false_state.instantiation_filename = self.instantiation_filename
            self.false_state.instantiation_lineno = self.instantiation_lineno

        # save the out_states
        self.out_states = [self.true_state, self.false_state]
        
        # append outcome to log
        self.log_attrs.append('outcome')
        
    def _enter(self):
        super(If, self)._enter()

        # reset outcome so we re-evaluate if called in loop
        # this will evaluate each conditional, we'll enter the first one that
        # evaluates to True. Note that the last one is always True because it's
        # the Else
        # must evaluate each cond
        self.outcome = [not v is False for v in val(self.cond)]
        self.selected_child = self.out_states[self.outcome.index(True)]
        self.selected_child.enter()  #TODO: queued call?

    def child_leave_callback(self, child):
        self.leave()

    def __enter__(self):
        # push self.true_state as current parent
        if not self.exp is None:
            self.exp._parents.append(self.true_state)
        return self

    def set_end_time(self):
        if self.selected_child is None:
            self.end_time = self.start_time
        else:
            self.end_time = self.selected_child.end_time


class Elif(Serial):
    """State to attach an elif to and If state.

    """
    def __init__(self, conditional, parent=None, save_log=True, name=None):
        # init the parent class
        super(Elif, self).__init__(parent=parent, duration=-1, 
                                   save_log=save_log, name=name)

        # we now know our parent, so ensure the previous child is
        # either and If or Elif state
        if self.parent is None:
            raise ValueError("The parent can not be None.")

        # grab the previous child (-2 because we are -1)
        prev_state = self.parent.children[-2]
        if not isinstance(prev_state, If):
            raise ValueError("The previous state must be an If or Elif state.")

        # have that previous If state grab this one
        prev_state.claim_child(self)

        # insert the conditional and state
        prev_state.cond.insert(-1, conditional)
        prev_state.out_states.insert(-1, self)

        
def Else(name="ELSE BODY"):
    """State to attach to the else of an If state.

    """

    # get the exp reference
    from experiment import Experiment
    try:
        exp = Experiment.last_instance()
    except AttributeError:
        raise AttributeError("You must first instantiate an Experiment.")

    # find the parent
    parent = exp._parents[-1]

    # find the previous child state (-1 because this is not a state)
    prev_state = parent.children[-1]
    
    # make sure it's the If
    if not isinstance(prev_state, If):
        raise ValueError("The previous state must be an If or Elif state.")

    # return the false_state (the last out_state)
    false_state = prev_state.out_states[-1]
    false_state.name = name
    filename, lineno = _get_calling_context(2)
    false_state.instantiation_filename = filename
    false_state.instantiation_lineno = lineno
    return false_state


class Loop(ParentState):
    """State that implements a loop.

    Loop over an iterable or run repeatedly while a conditional 
    evaluates to True. Loop is used in similar fashion to for 
    and while statements in Python.

    Parameters
    ----------
    iterable : object
    	Process to iterate through while a conditional evaluates to True
    shuffle : bool
        Whether to shuffle the iterable before the loop. Note that this will
        only work for iterables and will evaluate and make a shallow copy
        of the iterable in order to shuffle it.
    conditional : bool,Ref
    	Object that evaluates to a bool to determine whether to continue
    parent : object
    	The parent state
    save_log : bool
    	If set to 'True,' details about the If state will be automatically saved 
    	in the log files.

    Properties
    ----------
    i : int
        Iteration of the loop
    current : obj
        Current value of the iterable
    
    Example
    -------
    block = [{'image':'cow.jpg'},{'image':'octopus.jpg'}]
    with Loop(block) as trial:
        Show(Image(trial.current['image']), 2.0)
        Wait(.5)
    
    The Loop will iterate over the list of dictionaries, showing an
    image from trial.current for 2.0 seconds, unshow it, and wait for
    0.5 seconds. The Loop will continue to iterate over the list,
    running the Show and Wait states, until all the items from the
    list are traversed.

    """

    #TODO: Implement this with an enclosed Serial instead, to consolidate functionality!
    
    def __init__(self, iterable=None, shuffle=False, conditional=True,
                 parent=None, save_log=True, name=None):
        super(Loop, self).__init__(parent=parent, duration=-1, 
                                   save_log=save_log, name=name)

        # otherwise, assume it's a list of dicts
        self.iterable = iterable
        self.shuffle = shuffle
        self.cond = conditional
        self.outcome = True

        # set to first in loop
        self.i = None
        self._shuffled = False

        self.body_state = Serial(parent=self, name="LOOP BODY")
        self.body_state.instantiation_filename = self.instantiation_filename
        self.body_state.instantiation_lineno = self.instantiation_lineno
        self.current_child = None

        # append outcome to log
        self.log_attrs.extend(['outcome', 'i'])

    @property
    def current(self):
        if self.iterable is None:
            return None # could possibly return self.i here
        else:
            return self['iterable'][self['i']]

    def iter_i(self):
        self.outcome = val(self.cond)
        if self.iterable is None:
            i = 0
            while self.outcome:
                yield i
                i += 1
                self.outcome = val(self.cond)
        else:
            if not self.outcome:
                return

            # see if shuffle
            if val(self.shuffle) and not self._shuffled:
                # eval and make a shallow copy
                self.iterable = val(self.iterable, recurse=False)[:]  #IKS: only evaluated on the first execution of the Loop state???
                random.shuffle(self.iterable)
                self._shuffled = True

            for i in xrange(len(self.iterable)):
                # dump log
                dump([self.get_log()],self.get_log_stream())  #???

                yield i

    def _enter(self):
        # get the parent enter
        super(Loop, self)._enter()

        self.outcome = None
        self.current_child = None
        self.i_iterator = self.iter_i()
        self.start_next_iteration(True)

    def start_next_iteration(self, finalize_if_done=False):
        try:
            self.i = self.i_iterator.next()
        except StopIteration:
            self.leave()
            if finalize_if_done:
                self.finalize()
            return
        self.current_child = self.body_state
        #TODO: use cloning and do this with child_leave_callback instead
        if self.current_child.active:
            dfsfhsfghfxg#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        self.current_child.enter()

    def child_finalize_callback(self, child):
        super(Loop, self).child_finalize_callback(child)
        self.start_next_iteration()

    def __enter__(self):
        # push self.body_state as current parent
        if not self.exp is None:
            self.exp._parents.append(self.body_state)
        return self

    def set_end_time(self):
        if self.current_child is None:
            self.end_time = self.start_time
        else:
            self.end_time = self.current_child.end_time


class Wait(State):
    """
    State that will wait a specified time in seconds.  It is possible
    to keep the state active or simply move the parent's state time
    ahead.
    
    Parameters
    ----------
    duration: float
    	Time in seconds to remain in the wait state
    jitter: float
    	Creates the upper bound of a uniform distribution from which a jitter
    	is randomly drawn each time Wait is executed. The uniform distribution
    	takes the lower and upper bounds of (duration, duration + jitter)
    stay_active: bool
    	Determines whether the Wait state remains active, based on current time
    	compared with the duration parameter
    parent: object
    	The parent state    
    save_log: bool
    	If set to 'True,' details about the Wait state will be automatically saved 
    	in the log files.	
    
    Example
    -------
    Wait(2.0, 1.0)
    	The state will wait for a duration drawn from a uniform distribution with range
    	(2.0, 3.0)
    
    """
    def __init__(self, duration=0.0, jitter=0.0, stay_active=False, 
                 parent=None, save_log=True, name=None):
        # init the parent class
        super(Wait, self).__init__(interval=-1, parent=parent, 
                                   duration=Ref(duration, jitter=jitter), 
                                   save_log=save_log, name=name)
        self.stay_active = stay_active

    def _callback(self):
        if (not self.stay_active or
            clock.now() >= self.state_time + self.duration):
            # we're done
            #self.interval = 0
            self.leave()


class ResetClock(State, RunOnEnter):
    """
    State that will reset the clock of its parent to a specific time
    (or now if not specified).
    
    Parameters
    ----------
    new_time: float
        New time to reset the clock of the parent state
    parent: object
        The parent state
    save_log: bool
    	If set to 'True,' details about the ResetClock state will be automatically saved 
    	in the log files.
    Examples
    --------
    ResetClock()
    
    Will reset the time of the parent state to now.
    """
    
    def __init__(self, new_time=None, parent=None, save_log=True, name=None):
        # init the parent class
        super(ResetClock, self).__init__(interval=0, parent=parent, 
                                         duration=0, 
                                         save_log=save_log,
                                         name=name)
        if new_time is None:
            # eval to now if nothing specified
            new_time = Ref(gfunc=lambda:clock.now())
        self.new_time = new_time

    def _callback(self):
        duration = val(self.new_time) - self.get_parent_state_time()  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        if duration > 0:
            self.advance_parent_state_time(duration)
    

class Func(State):
    """
    State that will call a Python function, passing this state as the
    first argument.
    
    Parameters
    ----------
    func: function
        A python function to be applied to the State
    interval: float
        The number of seconds to wait between each call of the python function
    duration: float
        Duration of the parent state. An interval of 0 means enter the state once, 
        -1 means every frame. Defaults to 0
    parent: object
        The parent state
    save_log: bool
        If set to 'True,' details about the ResetClock state will be automatically saved 
        in the log files.
    
    Example
    -------
    Func(str(), StateA)
    Calls python function str(), converting the output of StateA into a string
    	
    """
    def __init__(self, func, args=None, kwargs=None, 
                 interval=0, parent=None, duration=0.0, 
                 save_log=True, name=None):
        # init the parent class
        super(Func, self).__init__(interval=interval, parent=parent, 
                                   duration=duration, 
                                   save_log=save_log,
                                   name=name)

        # set up the state
        self.func = func
        self.args = args
        if self.args is None:
            self.args = []
        self.kwargs = kwargs
        if self.kwargs is None:
            self.kwargs = {}

    def _callback(self):
        # process the refs
        args = val(self.args)
        kwargs = val(self.kwargs)
        self.res = self.func(self, *args, **kwargs)
    

class Debug(State):
    """
    Evaluate the specified kwargs and print them to standard out.

    Useful for debugging a state machine as the name implies.
    
    Parameters
    ----------
    parent: object
    	The parent state
    save_log: bool
    	If set to 'True,' details about the Debug state will be automatically saved 
    	in the log files.
    kwargs : dict
        key, value pairs to be evaluated and printed to stdout
    
    Example
    -------
    Print out the show time of a Show state:
        Debug(show_time=txt['show_time'])

    """
    def __init__(self, parent=None, save_log=False, name=None, **kwargs):
        # init the parent class
        super(Debug, self).__init__(interval=0, parent=parent,
                                   duration=0,
                                   save_log=save_log,
                                   name=name)

        # set up the state
        self.kwargs = kwargs

    def _callback(self):
        # process the refs
        #kwargs = {key: val(value) for (key, value) in self.kwargs}
        print 'DEBUG:', val(self.kwargs)


class PrintTrace(State):
    def __init__(self, parent=None, save_log=False, name=None):
        # init the parent class
        super(PrintTrace, self).__init__(interval=0, parent=parent,
                                         duration=0,
                                         save_log=save_log,
                                         name=name)

    def _callback(self):
        self.print_trace()


if __name__ == '__main__':

    from experiment import Experiment, Set, Get

    def print_dt(state, *txt):
        print txt, clock.now()-state.state_time

    def print_actual_duration(state, target):
        print target.end_time - target.start_time

    exp = Experiment()

    #Debug(width=exp['window'].width, height=exp['window'].height)  #!!!!!!!!!!!!!!!!!!!!!!

    with Loop(range(10)) as loop:
        with If(loop.current > 6):
            Func(print_dt, args=["True"])
        with Elif(loop.current > 4):
            Func(print_dt, args=["Trueish"])
        with Elif(loop.current > 2):
            Func(print_dt, args=["Falsish"])
        with Else():
            Func(print_dt, args=["False"])

    # with implied parents
    block = [{'val':i} for i in range(3)]
    Set('not_done',True)
    with Loop(conditional=Get('not_done')) as outer:
        Debug(i=outer['i'])
        with Loop(block, shuffle=True) as trial:
            Func(print_dt, args=[trial.current['val']])
            Wait(1.0)
            If(trial.current['val']==block[-1],
               Wait(2.))
        If(outer['i']>=3,Set('not_done',False))
        
    block = range(3)
    with Loop(block) as trial:
        Func(print_dt, args=[trial.current])
        Wait(1.0)
        If(trial.current==block[-1],
           Wait(2.))


    If(True, 
       Func(print_dt, args=["True"]),
       Func(print_dt, args=["False"]))
    Wait(1.0)
    If(False, 
       Func(print_dt, args=["True"]),
       Func(print_dt, args=["False"]))
    Wait(2.0)
    If(False, Func(print_dt, args=["True"])) # won't do anything
    Func(print_dt, args=["two"])
    Wait(3.0)
    with Parallel():
        with Serial():
            Wait(1.0)
            Func(print_dt, args=['three'])
        Func(print_dt, args=['four'])
    Wait(2.0)

    block = [{'text':'a'},{'text':'b'},{'text':'c'}]
    with Loop(block) as trial:
        Func(print_dt, args=[trial.current['text']])
        Wait(1.0)

    Func(print_dt, args=['before meanwhile 1'])
    Wait(1.0)
    with Meanwhile(name="First Meanwhile") as mw:
        Wait(15.0)
    Func(print_dt, args=['after meanwhile 1'])
    Func(print_actual_duration, args=(mw,))

    Func(print_dt, args=['before meanwhile 2'])
    Wait(5.0)
    with Meanwhile() as mw:
        PrintTrace()
        Wait(1.0)
    Func(print_dt, args=['after meanwhile 2'])
    Func(print_actual_duration, args=(mw,))

    Func(print_dt, args=['before untildone 1'])
    Wait(15.0)
    with UntilDone(name="UntilDone #1") as ud:
        Wait(1.0)
        PrintTrace()
    Func(print_dt, args=['after untildone 1'])
    Func(print_actual_duration, args=(ud,))

    Func(print_dt, args=['before untildone 2'])
    Wait(1.0)
    with UntilDone() as ud:
        Wait(5.0)
    Func(print_dt, args=['after untildone 2'])
    Func(print_actual_duration, args=(ud,))

    Wait(2.0, stay_active=True)  #TODO: eliminate need for stay_active

    exp.run()


    # # with explicit parents
    # If(True, 
    #    Func(print_dt, args=["True"], interval=0.0),
    #    Func(print_dt, args=["False"], interval=0.0),
    #    parent=exp)
    # Wait(1.0, parent=exp)
    # If(False, 
    #    Func(print_dt, args=["True"], interval=0.0),
    #    Func(print_dt, args=["False"], interval=0.0),
    #    parent=exp)
    # Wait(2.0, parent=exp)
    # Func(print_dt, args=["two"], interval=0.0, parent=exp)
    # Wait(3.0, parent=exp)
    # with Parallel(parent=exp) as trial:
    #     with Serial(parent=trial) as x:
    #         Wait(1.0, parent=x)
    #         Func(print_dt, args=['three'], interval=0.0, parent=x)
    #     Func(print_dt, args=['four'], interval=0.0, parent=trial)
    #     print trial.children
    # Wait(2.0, stay_active=True, parent=exp)

