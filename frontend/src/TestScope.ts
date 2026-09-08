import {createContext} from 'react';

/** A scoped API namespace; ordinary conversations keep the default namespace. */
export const TestScope = createContext<string | undefined>(undefined);
