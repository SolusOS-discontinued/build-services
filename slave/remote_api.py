from piston_mini_client import PistonAPI, returns_json, PistonResponseObject, returns_list_of
from piston_mini_client import PistonSerializable
from piston_mini_client.validators import validate, validate_pattern

class QueueResponse (PistonResponseObject):
	def __str__(self):
		return "<Package: %s>" % self.name

class QueueRequest (PistonSerializable):
	
	_atts = ('name', 'build_status')

class QueueStatusRequest (PistonSerializable):
	_atts = ('current', 'package_name', 'length')
					
class QueueAPI(PistonAPI):
    
    def __init__(self, remote_uri=None, auth=None):
        self.default_service_root = remote_uri
                
        PistonAPI.__init__(self, auth=auth)
        
    @returns_list_of (QueueResponse)
    def build_queue(self, queue_id):
        return self._get('queue/%d' % int(queue_id))

    def update_status (self, queue_id, request=None):
        return self._put ('queue/%d/' % int(queue_id), data=request)
        
    def update_queue (self, queue_id, request=None):
        return self._put ('queuestatus/%d/' % int(queue_id), data=request)
