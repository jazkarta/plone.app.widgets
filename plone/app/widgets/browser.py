from AccessControl import getSecurityManager
from AccessControl import Unauthorized
import json
import inspect
from zope.component import queryUtility
from zope.schema.interfaces import IVocabularyFactory
from Products.Five import BrowserView
from plone.app.vocabularies.interfaces import ISlicableVocabulary
from Products.ZCTextIndex.ParseTree import ParseError


_permissions = {
    'plone.app.vocabularies.Users': 'Modify portal content',
    'plone.app.vocabularies.Catalog': 'View',
    'plone.app.vocabularies.Keywords': 'Modify portal content'
}

def _parseJSON(s):
    if isinstance(s, basestring):
        s = s.strip()
        if (s.startswith('{') and s.endswith('}')) or \
                (s.startswith('[') and s.endswith(']')): # detect if json
            return json.loads(s)
    return s


_unsafe_metadata = ['Creator', 'listCreators']
_safe_callable_metadata = ['getURL', 'getPath']


class VocabularyView(BrowserView):

    def error(self):
        return json.dumps({
            'results': [],
            'total': 0,
            'error': True
        })


    def __call__(self):
        """
        Accepts GET parameters of:
        name: Name of the vocabulary
        query: string or json object of criteria and options.
            json value consists of a structure:
                {
                    criteria: object,
                    sort_on: index,
                    sort_order: (asc|reversed)
                }
        attributes: comma seperated, or json object list
        batch: {
            page: 1-based page of results,
            size: size of paged results
        }
        """
        self.request.response.setHeader("Content-type", "application/json")

        factory_name = self.request.get('name', None)
        if not factory_name:
            return json.dumps({'error': 'No factory provided.'})
        if factory_name not in _permissions:
            return json.dumps({'error': 'Vocabulary lookup not allowed'})
        sm = getSecurityManager()
        if not sm.checkPermission(_permissions[factory_name], self.context):
            raise Unauthorized('You do not have permission to use this vocabulary')
        factory = queryUtility(IVocabularyFactory, factory_name)
        if not factory:
            return json.dumps({
                'error': 'No factory with name "%s" exists.' % factory_name})

        # check if factory excepts query argument
        query = _parseJSON(self.request.get('query', ''))
        attributes = _parseJSON(self.request.get('attributes', ''))
        if isinstance(attributes, basestring) and attributes:
            attributes = attributes.split(',')
        batch = _parseJSON(self.request.get('batch', ''))
        factory_spec = inspect.getargspec(factory.__call__)
        try:
            if query and len(factory_spec.args) >= 3 and \
                    factory_spec.args[2] == 'query':
                if len(factory_spec.args) >= 4 and \
                        factory_spec.args[3] == 'batch':
                    vocabulary = factory(self.context, query, batch)
                else:
                    vocabulary = factory(self.context, query)
            else:
                vocabulary = factory(self.context)
        except (TypeError, ParseError):
            return self.error()

        try:
            total = len(vocabulary)
        except AttributeError:
            total = 0 # do not error if object does not support __len__
                      # we'll check again later if we can figure some size out
        if 'size' not in batch or 'page' not in batch:
            batch = None # batching not providing correct options
        if batch and ISlicableVocabulary.providedBy(vocabulary):
            # must be slicable for batching support
            start = (batch['page'] - 1) * batch['size']
            end = start + batch['size']
            vocabulary = vocabulary[start:end]

        items = []

        if attributes:
            base_path = '/'.join(self.context.getPhysicalPath())
            for vocab_item in vocabulary:
                item = {}
                for attr in attributes:
                    key = attr
                    if ':' in attr:
                        key, attr = attr.split(':', 1)
                    if attr in _unsafe_metadata:
                        continue
                    if key == 'path':
                        attr = 'getPath'
                    vocab_value = vocab_item.value
                    val = getattr(vocab_value, attr, None)
                    if callable(val):
                        if attr in _safe_callable_metadata:
                            val = val()
                        else:
                            continue
                    if key == 'path':
                        val = val[len(base_path):]
                    item[key] = val
                items.append(item)
        else:
            for item in vocabulary:
                items.append({'id': item.token, 'text': item.title})

        if total == 0:
            total = len(items)

        return json.dumps({
            'results': items,
            'total': total
        })

