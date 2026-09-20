# Field communication

Status: future P2 product contract; implementation and device acceptance pending.

This is an STO-authored contract for PL15, supported by PL4 delivery and PL5
offline operation. The authoritative scope and status are in
`docs/goals/roadmap.json`; the architecture boundary is
`docs/adr/ADR-016-field-communication-offline-delivery-and-execution-authority.md`.
It does not change P1 evidence requirements or authorise P2 implementation.

## Ordinary communication

An ordinary field communication should require no more effort than sending the
equivalent WhatsApp message. This is a field-usability acceptance goal, not a
claim that STO matches WhatsApp's feature set or measured global performance.

- A normal message needs no mandatory classification form. Open the relevant
  conversation, type and send. Activity context is inherited when entering
  from an activity; users can see or change that association without re-entering
  the same identifiers. An unlinked ordinary message is still valid.
- Useful cached/current state appears without unnecessary network blocking.
  Clearly distinguish cached information from a confirmed current schedule.
- Local send appears immediately with an unobtrusive, understandable queued
  state. The user can keep communicating or inspecting activities while work
  waits to synchronise. Queued does not mean received by the server or another
  person.
- Poor connectivity normally needs no manual retry. Recovery resumes
  automatically when connectivity and authorised access return. Show a
  meaningful action for a permission, session or domain problem that requires
  the user's attention; never silently discard work or falsely report success.
- Large touch targets, minimal navigation and accessible text support practical
  field use. Review the interaction on actual devices with field users; no new
  arbitrary millisecond target is introduced for ordinary messages or media.

Execution, Critical and Housekeeping are the initial communication
configuration. They are destinations/views to trial, not fixed domain
categories or a demand to classify every message. Initial capabilities are
text, replies, mentions, simple reactions, timestamps, activity context and
activity deep links. Author and queued/accepted state remain clear.

Useful system and execution events may appear in the same timeline with a
distinct label and link to their source. A person's "this is critical" and the
schedule's calculated criticality are displayed as different facts. Historical
calculated context identifies the schedule version it described; it is not
silently relabelled as current when the critical path changes.

## Communication does not change the schedule

The following example is synthetic: "A-101 bolts seized. Probably another
45 min." is descriptive communication. Neither it nor "A-101 done" changes
actual dates, remaining duration, progress, live schedule or approved forecast.
Photos, markup, replies and reactions cannot make those changes either.

A message may offer **Mark complete** or **Update remaining duration**. Taking
that action opens the explicit execution operation for that activity and shows
what will be submitted. It requires the appropriate permission, validation and
separate audit. A pending execution command remains pending until accepted;
its resulting live change is visibly unreviewed until the review process says
otherwise. Communication permission grants no planner or supervisor powers.

Supervisor/planner review remains an explicit workflow. A reply, reaction,
Critical posting, notification acknowledgement or viewing an image cannot
approve progress, publish a scenario or move the approved forecast. Correcting
accepted communication preserves its history; it does not rewrite an execution
record. Communication, media and delivery/notification state do not change
schedule hashes.

## Photographs and markup

Take a photograph or select one already on the device, mark it with an arrow,
circle or text, and send or queue it while continuing field work. Full media
transfer must not block further messages or execution reporting.

The source image survives markup unchanged. Keep the original independently of
the annotation, with a field-optimised copy where useful, a recoverable
annotation representation and a rendered annotated image where useful for
viewing. A later annotation revision remains traceable to its original; a
render is not a replacement for source evidence.

The interface distinguishes a locally queued photo, an accepted message whose
photo is still pending, an available photo and a transfer needing attention.
An interrupted transfer recovers without duplicate message or attachment
records. Original, annotation and activity association survive reconnect and
the supported app lifecycle. Missing media is shown honestly, never as a
completed upload. Source preservation does not imply that a photo independently
proves its claimed time or contents.

## Offline work, identity and access

Text, supported execution operations and media can be queued offline. Queued
work survives application process termination and reopening. The supported
device-restart and upgrade behaviour must be established during the PL5 trial;
an upgrade must preserve queued work or provide an explicit safe recovery path.
Suspension or a platform's background limits cannot be presented as successful
delivery. Reopening must recover saved work even where background transfer is
not available.

Keep the originating actor, project and activity association. On re-import,
existing communication still links to its historical activity context. If the
activity is no longer present or cannot be reconciled, show that fact instead
of silently linking to a similarly named task. Work-order and equipment context
can be added later; communication does not depend on CMMS integration.

Offline creation does not guarantee acceptance after session expiry, logout,
account disable, revoked membership or changed permissions. Reauthentication
may resume work still authorised for its original actor/project. Another
account must not inherit, see or submit that queue. Show held/rejected work
truthfully under the defined access and retention policy. Logout clears
protected content and does not claim remote revocation while that outcome is
unconfirmed.

PL4/PL5 design must establish the long-offline access limits, device-loss
response, local storage limits and safe queued-work recovery. Local access
cannot instantly learn that a remote membership was revoked. Attachment access
must be protected along with the message, including original images and
previews. Cleanup must account for uploaded media with no accepted message and
accepted messages whose media is incomplete; pending work must not disappear
through silent eviction.

## Notifications and later workflows

Provide useful notifications for normal messages, mentions, replies, critical
communication and relevant linked-activity updates, respecting user
preferences and project permissions. Notifications open the permitted activity
or conversation after authentication. A notification is a prompt to retrieve
current permitted content, not proof of delivery, review or a guaranteed
critical alert. Repeated delivery must not create duplicate content.

PL9 later turns existing messages and evidence into structured problems and
actions with owner, due date, status and handover visibility. PL10 later adds
critical watch, near-critical detection, escalation and reporting periods.
Neither needs a replacement messaging or media subsystem. Voice, video,
arbitrary nested teams/channels, general collaboration, rich incident rooms,
automated handover, advanced critical analytics and AI operational summaries
are outside initial PL15.

## Mandatory PL15 acceptance

Run an integrated trial on real devices with permitted test accounts and
supported activities. Record device/OS/app builds, network conditions and
lifecycle steps in `docs/evidence/`; cover iOS and Android, not only a desktop
offline simulation. The thin PL5 experiment informs architecture and effort;
the finished PL15 experience must satisfy this contract independently of that
experiment's result.

1. Device A opens Execution and sends an ordinary message, inheriting or
   selecting an activity association. Device B receives it with that link.
2. A captures or selects a photo, annotates it with arrow/circle/text and sends
   or queues it. Continue ordinary field use while full media transfer waits.
3. Disconnect both devices. Queue further communication and supported
   execution reports for the original three-task offline scenario. Terminate
   and reopen the app processes while offline; queued content remains usable.
4. Reconnect. Synchronisation resumes automatically, retaining local creation
   facts and canonical server acceptance order. The other device receives
   each accepted record without duplicate messages, attachments or execution
   effects. Activity associations survive.
5. Interrupt a media transfer, including a lost acknowledgement after server
   acceptance. Recover it without a second attachment record. Demonstrate
   message-accepted/media-pending and photo-uploaded/message-pending recovery,
   preserving the original, annotation and rendered result as required above.
6. Observe an isolated communication-only segment: text, reply, mention,
   reaction, photo, annotation and notification/delivery changes leave
   execution state, schedule state and hashes unchanged. Include a message
   whose words imply completion or delay.
7. Submit a separate explicit, authorised progress or remaining-duration
   command against the same supported activity. Show its independent audit,
   S7 live recalculation and Device B's subscribed update. Approved forecast
   remains unchanged until the supervisor/planner review permits it.
8. Exercise replies, mentions, simple reactions and activity deep links,
   including a push deep link after suspend/resume and reauthentication.
   Exercise session expiry and membership revoked while offline: permitted
   work can resume, refused work is explained, and account switching cannot
   expose or reattribute another actor's queue or attachments.

Record platform limitations separately from the required termination/reopen
proof. Device restart, app upgrade and bounded background/media recovery need
an explicit supported outcome. An unexecuted or failing required case stays
open; a PoC screenshot or successful text send is not full slice acceptance.
